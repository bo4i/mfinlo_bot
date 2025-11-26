import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

from app.db import get_db
from app.db.models import Admin, Category, Request, Subcategory, User
from app.keyboards.admin import get_admin_new_request_keyboard
from app.keyboards.main import (
    get_aho_issue_keyboard,
    get_aho_other_subcategory_keyboard,
    get_comment_skip_keyboard,
    get_photo_skip_keyboard,
    get_request_confirmation_keyboard,
    get_urgency_keyboard,
)
from app.states.requests import NewRequestStates
from app.services.categories import ensure_categories_exist

logger = logging.getLogger(__name__)

router = Router()


async def _track_temporary_message(state: FSMContext | None, message_id: int | None) -> None:
    if not state or not message_id:
        return

    user_data = await state.get_data()
    existing_ids = set(user_data.get("messages_to_cleanup", []))
    existing_ids.add(message_id)
    await state.update_data(messages_to_cleanup=list(existing_ids))


async def update_request_prompt(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup=None,
    *,
    edit_existing: bool = True,
    state: FSMContext | None = None,
    track_message: bool = True,
) -> int:
    """Edit an existing prompt message or send a new one if editing fails."""
    if edit_existing and message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            if track_message:
                await _track_temporary_message(state, message_id)
            return message_id
        except TelegramBadRequest as exc:
            error_text = str(exc)
            if "message is not modified" in error_text:
                logger.debug(
                    "Сообщение %s не изменилось при попытке редактирования, пропускаем обновление",
                    message_id,
                )
                if track_message:
                    await _track_temporary_message(state, message_id)
                return message_id
            logger.warning("Не удалось отредактировать сообщение %s: %s", message_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отредактировать сообщение %s: %s", message_id, exc)

    sent_message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    if track_message:
        await _track_temporary_message(state, sent_message.message_id)
    return sent_message.message_id


async def _cleanup_request_messages(bot: Bot, chat_id: int, state: FSMContext) -> None:
    user_data = await state.get_data()
    message_ids = user_data.get("messages_to_cleanup", [])
    for message_id in message_ids:
        if not message_id:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось удалить сообщение %s: %s", message_id, exc)

    await state.update_data(messages_to_cleanup=[])


def _parse_duration_minutes(duration_text: str) -> int | None:
    sanitized = duration_text.strip().lower()
    if not sanitized:
        return None

    time_match = re.match(r"^(?P<hours>\d{1,2})\s*[:.]\s*(?P<minutes>\d{1,2})$", sanitized)
    if time_match:
        hours = int(time_match.group("hours"))
        minutes = int(time_match.group("minutes"))
        return hours * 60 + minutes

    number_match = re.search(r"(\d+(?:[.,]\d+)?)", sanitized)
    if not number_match:
        return None

    number_value = float(number_match.group(1).replace(",", "."))

    if "час" in sanitized or "ч" in sanitized:
        return int(number_value * 60)
    if "мин" in sanitized:
        return int(number_value)
    return int(number_value * 60)


def _find_overlapping_car_request(db_session, start_at: datetime, end_at: datetime) -> Request | None:
    return (
        db_session.query(Request)
        .filter(
            Request.request_type == "AHO",
            Request.car_start_at.isnot(None),
            Request.car_end_at.isnot(None),
            Request.car_start_at < end_at,
            Request.car_end_at > start_at,
        )
        .order_by(Request.car_start_at)
        .first()
    )


def _get_sorted_categories(db_session) -> list[Category]:
    return (
        db_session.query(Category)
        .order_by(Category.request_count.desc(), Category.name.asc())
        .all()
    )


def _get_sorted_subcategories(db_session, category_id: int) -> list[Subcategory]:
    return (
        db_session.query(Subcategory)
        .filter(Subcategory.category_id == category_id)
        .order_by(Subcategory.request_count.desc(), Subcategory.name.asc())
        .all()
    )


def _build_categories_keyboard(categories: list[Category]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"{idx + 1}. {category.name}", callback_data=f"cat_{category.id}")]
        for idx, category in enumerate(categories)
    ]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="category_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_subcategories_keyboard(subcategories: list[Subcategory], category_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{idx + 1}. {subcategory.name}",
                callback_data=f"sub_{subcategory.id}",
            )
        ]
        for idx, subcategory in enumerate(subcategories)
    ]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"back_to_cat_{category_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _prompt_for_photo(
    bot: Bot,
    chat_id: int,
    prompt_message_id: int | None,
    state: FSMContext,
    description: str,
    *,
    attachment_required: bool = False,
    prompt_text: str | None = None,
) -> None:
    if not prompt_text:
        prompt_text = (
            "Прикрепите фото или документ (если это необходимо) или нажмите «Пропустить»."
            if not attachment_required
            else "Пожалуйста, прикрепите необходимый файл (фото или документ). Это обязательный шаг."
        )

    prompt_message_id = await update_request_prompt(
        bot=bot,
        chat_id=chat_id,
        message_id=prompt_message_id,
        text=prompt_text,
        reply_markup=None if attachment_required else get_photo_skip_keyboard(),
    )
    await state.update_data(
        description=description,
        prompt_message_id=prompt_message_id,
        attachment_required=attachment_required,
        photo_prompt_text=prompt_text,
    )
    await state.set_state(NewRequestStates.waiting_for_photo)


async def _prompt_for_comment(
    bot: Bot,
    chat_id: int,
    prompt_message_id: int | None,
    state: FSMContext,
    *,
    comment_required: bool = True,
) -> None:
    prompt_message_id = await update_request_prompt(
        bot=bot,
        chat_id=chat_id,
        message_id=prompt_message_id,
        text="Опишите дополнительные детали проблемы — так мы сможем решить вашу заявку максимально быстро.",
        reply_markup=None if comment_required else get_comment_skip_keyboard(),
        edit_existing=False,
        state=state,
    )
    await state.update_data(
        prompt_message_id=prompt_message_id,
        comment_required=comment_required,
    )
    await state.set_state(NewRequestStates.waiting_for_comment)


async def _prompt_for_confirmation(bot: Bot, chat_id: int, state: FSMContext) -> None:
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    request_type = user_data.get("request_type", "")
    description = user_data.get("description", "")
    urgency = user_data.get("urgency")
    due_date = user_data.get("due_date")
    comment = user_data.get("comment")
    category_name = user_data.get("category_name")
    subcategory_name = user_data.get("subcategory_name")
    planned_date = user_data.get("planned_date")

    urgency_text = "Как можно скорее" if urgency == "ASAP" else f"К {due_date}" if due_date else "Не указана"
    request_name = "ИТ" if request_type == "IT" else "АХО" if request_type == "AHO" else ""

    description_line = description
    if category_name:
        description_line = f"Категория: {category_name}"
    if subcategory_name:
        description_line += f"\nПодкатегория: {subcategory_name}"

    summary_lines = [
        "Проверьте данные заявки:",
        f"Тип: {request_name}",
        f"Описание: {description_line}",
        f"Срочность: {urgency_text}",
    ]
    if planned_date:
        summary_lines.append(f"Дата исполнения: {planned_date}")
    summary_lines.append(f"Комментарий: {comment}" if comment else "Комментарий: отсутствует")
    summary_lines.append("Отправить заявку?")

    prompt_message_id = await update_request_prompt(
        bot=bot,
        chat_id=chat_id,
        message_id=prompt_message_id,
        text="\n".join(summary_lines),
        reply_markup=get_request_confirmation_keyboard(),
        edit_existing=False,
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_confirmation)



@router.message(F.text.in_({"Создать ИТ-заявку", "Создать АХО-заявку"}))
async def start_new_request(message: Message, state: FSMContext) -> None:
    with get_db() as db:
        user = db.query(User).filter(User.id == message.from_user.id).first()

        if not user or not user.registered:
            await message.answer("Вы не зарегистрированы или регистрация не завершена. Пожалуйста, начните с команды /start.")
            return
    await _track_temporary_message(state, message.message_id)
    request_type = "IT" if message.text == "Создать ИТ-заявку" else "AHO"
    await state.update_data(
        request_type=request_type,
        comment_required=request_type != "AHO",
    )

    if request_type == "AHO":
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=None,
            text="Выберите тип проблемы для АХО-заявки:",
            reply_markup=get_aho_issue_keyboard(),
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.choosing_aho_issue)
        return

    with get_db() as db:
        ensure_categories_exist(db)
        categories = _get_sorted_categories(db)

    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=None,
        text="Выберите категорию ИТ-заявки:",
        reply_markup=_build_categories_keyboard(categories),
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.choosing_category)


@router.callback_query(NewRequestStates.choosing_category, F.data == "category_cancel")
async def cancel_category_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Отмена")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    await callback_query.bot.send_message(
        chat_id=callback_query.message.chat.id,
        text="Создание заявки отменено. Вы можете начать заново с помощью команды /start.",
    )
    await _cleanup_request_messages(callback_query.bot, callback_query.message.chat.id, state)
    await state.clear()


@router.callback_query(NewRequestStates.choosing_category, F.data.startswith("cat_"))
async def process_category_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    try:
        category_id = int(callback_query.data.replace("cat_", ""))
    except ValueError:
        await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Не удалось определить категорию. Попробуйте снова.",
            edit_existing=False,
            state=state,
        )
        return

    with get_db() as db:
        category = db.query(Category).filter(Category.id == category_id).first()
        if not category:
            await update_request_prompt(
                bot=callback_query.bot,
                chat_id=callback_query.message.chat.id,
                message_id=prompt_message_id,
                text="Категория не найдена. Попробуйте выбрать заново.",
                edit_existing=False,
                state=state,
            )
            categories = _get_sorted_categories(db)
            await state.update_data(prompt_message_id=prompt_message_id)
            await callback_query.message.edit_reply_markup(reply_markup=_build_categories_keyboard(categories))
            return

        subcategories = _get_sorted_subcategories(db, category_id)

    if not subcategories:
        await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Для выбранной категории пока нет подкатегорий. Попробуйте выбрать другую категорию.",
            edit_existing=False,
            state=state,
        )
        with get_db() as db:
            categories = _get_sorted_categories(db)
        await state.update_data(prompt_message_id=prompt_message_id)
        await callback_query.message.edit_reply_markup(reply_markup=_build_categories_keyboard(categories))
        return

    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text=f"Категория: {category.name}\nВыберите подкатегорию:",
        reply_markup=_build_subcategories_keyboard(subcategories, category_id),
        state=state,
    )
    await state.update_data(
        prompt_message_id=prompt_message_id,
        category_id=category_id,
        category_name=category.name,
    )
    await state.set_state(NewRequestStates.choosing_subcategory)


@router.callback_query(NewRequestStates.choosing_subcategory, F.data.startswith("back_to_cat_"))
async def back_to_categories(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    with get_db() as db:
        categories = _get_sorted_categories(db)
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text="Выберите категорию ИТ-заявки:",
        reply_markup=_build_categories_keyboard(categories),
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.choosing_category)


@router.callback_query(NewRequestStates.choosing_subcategory, F.data.startswith("sub_"))
async def process_subcategory_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    category_id = user_data.get("category_id")

    try:
        subcategory_id = int(callback_query.data.replace("sub_", ""))
    except ValueError:
        await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Не удалось определить подкатегорию. Попробуйте снова.",
            edit_existing=False,
            state=state,
        )
        return

    with get_db() as db:
        subcategory = db.query(Subcategory).filter(Subcategory.id == subcategory_id).first()
    if not subcategory:
        await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Подкатегория не найдена. Попробуйте снова.",
            edit_existing=False,
            state=state,
        )
        return

    description = f"{user_data.get('category_name', '')} - {subcategory.name}"
    await state.update_data(
        prompt_message_id=prompt_message_id,
        subcategory_id=subcategory_id,
        subcategory_name=subcategory.name,
        description=description,
    )
    await _prompt_for_photo(
        callback_query.bot,
        callback_query.message.chat.id,
        prompt_message_id,
        state,
        description,
    )


@router.callback_query(NewRequestStates.choosing_aho_issue, F.data.startswith("aho_issue_"))
async def process_aho_issue_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    selection = callback_query.data.replace("aho_issue_", "")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")

    issue_descriptions = {
        "supplies": "Заявка на канцтовары",
        "lamps": "Замена световых ламп",
        "aircon": "Починка кондиционера",
        "car": "Пользование авто",
        "household": "Заявка хозтовары",
        "heating": "Регулировка отопления",
        "repairs": "Заявка на мелкие ремонтные работы",
    }

    if selection == "other":
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Выберите подкатегорию для раздела «Прочее»:",
            reply_markup=get_aho_other_subcategory_keyboard(),
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id, base_issue="Прочее", comment_required=False)
        return

    if selection == "car":
        calendar_markup = await SimpleCalendar().start_calendar()
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Выберите дату поездки на авто:",
            reply_markup=calendar_markup,
            state=state,
        )
        await state.update_data(
            description=issue_descriptions.get(selection, ""),
            prompt_message_id=prompt_message_id,
        )
        await state.set_state(NewRequestStates.waiting_for_car_date)
        return

    description = issue_descriptions.get(selection)
    if not description:
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Создание заявки отменено. Вы можете начать заново с помощью команды /start.",
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    if selection == "supplies":
        await _prompt_for_photo(
            callback_query.bot,
            callback_query.message.chat.id,
            prompt_message_id,
            state,
            description,
            attachment_required=True,
            prompt_text=(
                "Прикрепите перечень канцтоваров файлом (фото или документ). "
                "Отправка файла обязательна для оформления заявки."
            ),
        )
        return

    if selection == "household":
        await _prompt_for_photo(
            callback_query.bot,
            callback_query.message.chat.id,
            prompt_message_id,
            state,
            description,
            attachment_required=True,
            prompt_text=(
                "Прикрепите перечень хозтоваров файлом (фото или документ). "
                "Отправка файла обязательна для оформления заявки."
            ),
        )
        return

    if selection == "repairs":
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text=(
                "Опишите, что нужно отремонтировать. После текста вы сможете при необходимости"
                " прикрепить фото или документ."
            ),
            edit_existing=False,
            state=state,
        )
        await state.update_data(base_issue=description, prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_description)
        return
    await _prompt_for_photo(callback_query.bot, callback_query.message.chat.id, prompt_message_id, state, description)


@router.callback_query(NewRequestStates.choosing_aho_issue, F.data == "aho_issue_cancel")
async def cancel_aho_issue_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Отмена")
    await callback_query.bot.send_message(
        chat_id=callback_query.message.chat.id,
        text="Создание заявки отменено. Вы можете начать заново с помощью команды /start.",
    )
    await _cleanup_request_messages(callback_query.bot, callback_query.message.chat.id, state)
    await state.clear()


@router.callback_query(NewRequestStates.choosing_aho_issue, F.data == "back_to_aho_issue")
async def back_to_aho_issue_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text="Выберите тип проблемы для АХО-заявки:",
        reply_markup=get_aho_issue_keyboard(),
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id, comment_required=False)


@router.callback_query(NewRequestStates.choosing_aho_issue, F.data.startswith("aho_other_"))
async def process_aho_other_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    selection = callback_query.data.replace("aho_other_", "")

    if selection == "cleaning":
        description = "Прочее - Уборка кабинета"
        await state.update_data(
            description=description,
            prompt_message_id=prompt_message_id,
            comment_required=True,
        )
        await _prompt_for_photo(
            callback_query.bot,
            callback_query.message.chat.id,
            prompt_message_id,
            state,
            description,
            prompt_text=(
                "Прикрепите фото или документ при необходимости (это необязательно). "
                "После этого укажем срочность выполнения."
            ),
        )
        return

    if selection == "custom":
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Опишите вашу заявку в категории «Прочее»:",
            edit_existing=False,
            state=state,
        )
        await state.update_data(
            base_issue="Прочее",
            prompt_message_id=prompt_message_id,
            comment_required=False,
        )
        await state.set_state(NewRequestStates.waiting_for_description)
        return

    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text="Не удалось определить выбранную подкатегорию. Попробуйте снова.",
        reply_markup=get_aho_other_subcategory_keyboard(),
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id)


@router.message(NewRequestStates.waiting_for_description)
async def process_description(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    if not message.text:
        user_data = await state.get_data()
        prompt_message_id = user_data.get("prompt_message_id")
        await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Пожалуйста, введите описание проблемы текстом.",
            edit_existing=False,
            state=state,
        )
        return

    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    base_issue = user_data.get("base_issue")
    description = f"{base_issue}: {message.text}" if base_issue else message.text
    await _prompt_for_photo(message.bot, message.chat.id, prompt_message_id, state, description)


@router.callback_query(NewRequestStates.waiting_for_car_date, SimpleCalendarCallback.filter())
async def process_car_date_selection(
    callback_query: CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext
) -> None:
    selected, selected_date = await SimpleCalendar().process_selection(callback_query, callback_data)

    if not selected:
        return

    await callback_query.answer()
    formatted_date = selected_date.strftime("%Y-%m-%d")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text=(
            f"Дата поездки: {formatted_date}\n"
            "Введите время начала поездки в формате ЧЧ:ММ (например, 10:00)."

        ),
        edit_existing=False,
        state=state,
    )
    await state.update_data(car_date=formatted_date, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_car_time)


@router.message(NewRequestStates.waiting_for_car_time)
async def process_car_time(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    time_text = (message.text or "").strip()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    car_date = user_data.get("car_date")

    if not car_date:
        calendar_markup = await SimpleCalendar().start_calendar()
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Произошла ошибка при выборе даты поездки. Пожалуйста, выберите дату снова.",
            reply_markup=calendar_markup,
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_car_date)
        return

    try:
        parsed_time = datetime.strptime(time_text, "%H:%M")
        normalized_time = parsed_time.strftime("%H:%M")
    except ValueError:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (например, 10:00).",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=prompt_message_id,
        text="Укажите продолжительность поездки (например, 2 часа).",
        edit_existing=False,
        state=state,
    )
    await state.update_data(car_time=normalized_time, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_car_duration)


@router.message(NewRequestStates.waiting_for_car_duration)
async def process_car_duration(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    duration_text = (message.text or "").strip()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    base_description = user_data.get("description", "Пользование авто")
    car_date = user_data.get("car_date")
    car_time = user_data.get("car_time")
    if not duration_text:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Пожалуйста, укажите продолжительность поездки (например, 2 часа).",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    duration_minutes = _parse_duration_minutes(duration_text)
    if duration_minutes is None or duration_minutes <= 0:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Не удалось распознать продолжительность. Укажите её в формате '2 часа' или '1:30'.",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    try:
        start_datetime = datetime.strptime(f"{car_date} {car_time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Произошла ошибка при определении даты или времени. Пожалуйста, введите время начала снова.",
            edit_existing=False,
            state=state,

        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_car_time)
        return

    end_datetime = start_datetime + timedelta(minutes=duration_minutes)

    with get_db() as db:
        overlapping_request = _find_overlapping_car_request(db, start_datetime, end_datetime)

    if overlapping_request:
        busy_date = overlapping_request.car_start_at.strftime("%d-%m")
        busy_from_time = overlapping_request.car_start_at.strftime("%H:%M")
        busy_to_time = overlapping_request.car_end_at.strftime("%H:%M")
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text=(
                "Автомобиль уже забронирован на это время. "
                f"Он занят {busy_date} с {busy_from_time} до {busy_to_time}.\n"
                "Выберите другое время начала поездки (ЧЧ:ММ)."
            ),
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_car_time)
        return

    await state.update_data(
        car_duration_text=duration_text,
        car_duration_minutes=duration_minutes,
        car_start_at=start_datetime.isoformat(),
        car_end_at=end_datetime.isoformat(),
    )

    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=prompt_message_id,
        text="Укажите место поездки.",
        edit_existing=False,
        state=state,
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_car_location)


    @router.message(NewRequestStates.waiting_for_car_location)
    async def process_car_location(message: Message, state: FSMContext) -> None:
        await _track_temporary_message(state, message.message_id)
        location_text = (message.text or "").strip()
        user_data = await state.get_data()
        prompt_message_id = user_data.get("prompt_message_id")
        car_date = user_data.get("car_date")
        car_time = user_data.get("car_time")
        duration_text = user_data.get("car_duration_text")
        car_start_at = user_data.get("car_start_at")
        base_description = user_data.get("description", "Пользование авто")

        if not location_text:
            prompt_message_id = await update_request_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                message_id=prompt_message_id,
                text="Пожалуйста, укажите место поездки.",
                edit_existing=False,
                state=state,
            )
            await state.update_data(prompt_message_id=prompt_message_id)
            return

        details = []
        if car_date:
            details.append(f"Дата: {car_date}")
        if car_time:
            details.append(f"время: {car_time}")
        if duration_text:
            details.append(f"продолжительность: {duration_text}")
        details.append(f"место: {location_text}")

        description = f"{base_description}. {'; '.join(details)}."
        car_start_formatted = None
        if car_start_at:
            try:
                car_start_formatted = datetime.fromisoformat(car_start_at).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                car_start_formatted = car_start_at
        await state.update_data(
            description=description,
            car_location=location_text,
            urgency="DATE",
            due_date=car_start_formatted,
        )
        await _prompt_for_confirmation(message.bot, message.chat.id, state)


async def _store_attachment_and_ask_urgency(
    message: Message, state: FSMContext, file_id: str, attachment_type: str
) -> None:
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=prompt_message_id,
        text="Файл прикреплён. Как срочно необходимо выполнить заявку?",
        reply_markup=get_urgency_keyboard(),
        edit_existing=False,
        state=state,
    )
    await state.update_data(
        attachment_file_id=file_id,
        attachment_type=attachment_type,
        prompt_message_id=prompt_message_id,
        attachment_required=False,
    )
    await state.set_state(NewRequestStates.waiting_for_urgency)

@router.message(NewRequestStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    photo_file_id = message.photo[-1].file_id
    await _store_attachment_and_ask_urgency(message, state, photo_file_id, "photo")


@router.message(NewRequestStates.waiting_for_photo, F.document)
async def process_document(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    document_file_id = message.document.file_id
    await _store_attachment_and_ask_urgency(message, state, document_file_id, "document")

@router.callback_query(NewRequestStates.waiting_for_photo, F.data == "skip_photo")
async def skip_photo(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Пропущено")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    if user_data.get("attachment_required"):
        prompt_text = user_data.get("photo_prompt_text") or (
            "Для этой заявки необходимо прикрепить файл (фото или документ). Отправьте его, пожалуйста."
        )
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text=prompt_text,
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text="Как срочно необходимо выполнить заявку?",
        reply_markup=get_urgency_keyboard(),
        state=state,
    )
    await state.update_data(
        attachment_file_id=None,
        attachment_type=None,
        prompt_message_id=prompt_message_id,
    )
    await state.set_state(NewRequestStates.waiting_for_urgency)


@router.message(NewRequestStates.waiting_for_photo)
async def handle_unexpected_photo_input(message: Message, state: FSMContext) -> None:
    user_data = await state.get_data()
    if user_data.get("attachment_required"):
        prompt_text = user_data.get("photo_prompt_text") or (
            "Не удалось обработать сообщение. Прикрепите обязательный файл (фото или документ)."
        )
        await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=user_data.get("prompt_message_id"),
            text=prompt_text,
            edit_existing=False,
            state=state,
        )
        return

    response = await message.answer(
        "Пожалуйста, отправьте фото, документ или нажмите кнопку «Пропустить»."
    )
    await _track_temporary_message(state, response.message_id)


@router.callback_query(NewRequestStates.waiting_for_urgency, F.data.in_({"urgency_asap", "urgency_date"}))
async def process_urgency_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    comment_required = user_data.get("comment_required", True)
    if callback_query.data == "urgency_asap":
        await state.update_data(urgency="ASAP")
        if comment_required:
            await _prompt_for_comment(
                callback_query.bot,
                callback_query.message.chat.id,
                prompt_message_id,
                state,
                comment_required=comment_required,
            )
        else:
            await _prompt_for_confirmation(callback_query.bot, callback_query.message.chat.id, state)
    elif callback_query.data == "urgency_date":
        await state.update_data(urgency="DATE")
        calendar_markup = await SimpleCalendar().start_calendar()
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Выберите желаемую дату выполнения заявки:",
            reply_markup=calendar_markup,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_date)


@router.callback_query(NewRequestStates.waiting_for_date, SimpleCalendarCallback.filter())
async def process_date_selection(
    callback_query: CallbackQuery,
    callback_data: SimpleCalendarCallback,
    state: FSMContext,
) -> None:
    selected, selected_date = await SimpleCalendar().process_selection(callback_query, callback_data)

    if not selected:
        return

    await callback_query.answer()
    formatted_date = selected_date.strftime("%Y-%m-%d")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text=(
            f"Дата: {formatted_date}\n"
            "Введите желаемое время в формате ЧЧ:ММ (например, 10:00)."
        ),
        edit_existing=False,
        state=state,
    )
    await state.update_data(selected_date=formatted_date, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_time)


@router.message(NewRequestStates.waiting_for_time)
async def process_time(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    time_text = (message.text or "").strip()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    selected_date = user_data.get("selected_date")

    if not selected_date:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Произошла ошибка при выборе даты. Попробуйте выбрать дату снова.",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_urgency)
        return

    try:
        parsed_datetime = datetime.strptime(f"{selected_date} {time_text}", "%Y-%m-%d %H:%M")
        normalized_date = parsed_datetime.strftime("%Y-%m-%d %H:%M")
        await state.update_data(due_date=normalized_date, prompt_message_id=prompt_message_id)
        comment_required = user_data.get("comment_required", True)
        if comment_required:
            await _prompt_for_comment(
                message.bot,
                message.chat.id,
                prompt_message_id,
                state,
                comment_required=comment_required,
            )
        else:
            await _prompt_for_confirmation(message.bot, message.chat.id, state)
    except ValueError:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (например, 10:00).",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)

@router.message(NewRequestStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    await _track_temporary_message(state, message.message_id)
    comment_text = (message.text or "").strip()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    comment_required = user_data.get("comment_required", True)

    if not comment_text:
        if comment_required:
            await update_request_prompt(
                bot=message.bot,
                chat_id=message.chat.id,
                message_id=prompt_message_id,
                text="Опишите дополнительные детали проблемы — так мы сможем решить вашу заявку максимально быстро.",
                edit_existing=False,
                state=state,
            )
            await state.update_data(prompt_message_id=prompt_message_id)
            return

        await state.update_data(comment=None, prompt_message_id=prompt_message_id)
        await _prompt_for_confirmation(message.bot, message.chat.id, state)
        return

    await state.update_data(comment=comment_text, prompt_message_id=prompt_message_id)
    await _prompt_for_confirmation(message.bot, message.chat.id, state)


@router.callback_query(NewRequestStates.waiting_for_comment, F.data == "skip_comment")
async def skip_comment(callback_query: CallbackQuery, state: FSMContext) -> None:
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    comment_required = user_data.get("comment_required", True)

    if comment_required:
        await callback_query.answer("Комментарий обязателен")
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Опишите дополнительные детали проблемы — так мы сможем решить вашу заявку максимально быстро.",
            edit_existing=False,
            state=state,
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    await callback_query.answer("Комментарий пропущен")
    await state.update_data(comment=None, prompt_message_id=prompt_message_id)
    await _prompt_for_confirmation(callback_query.bot, callback_query.message.chat.id, state)



@router.callback_query(NewRequestStates.waiting_for_confirmation, F.data == "confirm_request")
async def confirm_request(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Заявка отправляется")
    await save_request(callback_query.message, state, callback_query.from_user.id, bot=callback_query.bot)


@router.callback_query(NewRequestStates.waiting_for_confirmation, F.data == "cancel_request")
async def cancel_request(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Заявка отменена")
    await callback_query.bot.send_message(
        chat_id=callback_query.message.chat.id,
        text="Создание заявки отменено. Вы можете начать заново с помощью команды /start.",
    )
    await _cleanup_request_messages(callback_query.bot, callback_query.message.chat.id, state)
    await state.clear()


async def save_request(message: Message, state: FSMContext, user_id: int, bot: Bot) -> None:
    user_data = await state.get_data()
    request_type = user_data.get("request_type")
    description = user_data.get("description")
    category_id = user_data.get("category_id")
    subcategory_id = user_data.get("subcategory_id")
    attachment_file_id = user_data.get("attachment_file_id")
    attachment_type = user_data.get("attachment_type")
    photo_file_id = attachment_file_id or user_data.get("photo_file_id")
    if photo_file_id and not attachment_type:
        attachment_type = "photo"
    urgency = user_data.get("urgency")
    due_date = user_data.get("due_date") if urgency == "DATE" else None
    prompt_message_id = user_data.get("prompt_message_id")
    comment = user_data.get("comment")
    attachment_type = attachment_type
    car_start_at_raw = user_data.get("car_start_at")
    car_end_at_raw = user_data.get("car_end_at")
    car_location = user_data.get("car_location")
    planned_date_raw = user_data.get("planned_date")

    car_start_at = None
    car_end_at = None
    planned_date = None
    if car_start_at_raw:
        try:
            car_start_at = datetime.fromisoformat(car_start_at_raw)
        except ValueError:
            car_start_at = None
    if car_end_at_raw:
        try:
            car_end_at = datetime.fromisoformat(car_end_at_raw)
        except ValueError:
            car_end_at = None
    if planned_date_raw:
        try:
            planned_date = datetime.strptime(planned_date_raw, "%Y-%m-%d")
        except ValueError:
            planned_date = None

    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            await bot.send_message(
                chat_id=message.chat.id,
                text="Произошла ошибка: пользователь не найден. Пожалуйста, попробуйте начать заново (/start).",
            )
            await _cleanup_request_messages(bot, message.chat.id, state)
            await state.clear()
            return

        new_request = Request(
            user_id=user_id,
            request_type=request_type,
            description=description,
            category_id=category_id,
            subcategory_id=subcategory_id,
            photo_file_id=photo_file_id,
            attachment_type=attachment_type,
            urgency=urgency,
            due_date=due_date,
            status="Принято",
            comment=comment,
            car_start_at=car_start_at,
            car_end_at=car_end_at,
            car_location=car_location,
            planned_date=planned_date,
        )
        db.add(new_request)

        if category_id:
            category = db.query(Category).filter(Category.id == category_id).first()
            if category:
                category.request_count = (category.request_count or 0) + 1
        if subcategory_id:
            subcategory = db.query(Subcategory).filter(Subcategory.id == subcategory_id).first()
            if subcategory:
                subcategory.request_count = (subcategory.request_count or 0) + 1

        db.commit()
        db.refresh(new_request)

        await bot.send_message(
            chat_id=message.chat.id,
            text="Заявка успешно создана, вы можете отслеживать её статус в «Мои заявки».",
        )
        await _cleanup_request_messages(bot, message.chat.id, state)
        await state.clear()
        await notify_admins(db, new_request, user, bot)
        logger.info("Заявка ID:%s от пользователя %s создана и отправлена администраторам.", new_request.id, user.id)


async def notify_admins(db_session, request: Request, user: User, bot: Bot) -> None:
    admin_type_filter = "IT_ADMIN" if request.request_type == "IT" else "AHO_ADMIN"
    admin_ids_to_notify = [admin.id for admin in db_session.query(Admin).filter(Admin.admin_type == admin_type_filter).all()]

    user_details = f"📞 Телефон: {user.phone_number}\n🏢 Организация: {user.organization}"
    if user.office_number:
        user_details += f"\n🚪 Кабинет: {user.office_number}"

    comment_block = f"\n💬 Комментарий: {request.comment}" if request.comment else ""
    category_block = ""
    if request.category or request.subcategory:
        category_lines = []
        if request.category:
            category_lines.append(f"Категория: {request.category.name}")
        if request.subcategory:
            category_lines.append(f"Подкатегория: {request.subcategory.name}")
        category_block = "\n" + "\n".join(category_lines)
    planned_date_text = None
    if request.due_date:
        planned_date_text = request.due_date
    elif request.planned_date:
        planned_date_text = request.planned_date.strftime("%Y-%m-%d")
    planned_date_block = f"\n📅 Дата исполнения: {planned_date_text}" if planned_date_text else ""

    request_info = (
        f"🚨 Новая заявка от {user.full_name} 🚨\n"
        f"{user_details}\n"
        f"📝 Описание: {request.description}{category_block}\n"
        f"⏰ Срочность: {'Как можно скорее' if request.urgency == 'ASAP' else f'К {request.due_date}'}{planned_date_block}{comment_block}\n"
        f"🆔 Заявка ID: {request.id}"
    )

    keyboard = get_admin_new_request_keyboard(request.id)

    for admin_id in admin_ids_to_notify:
        try:
            if request.photo_file_id:
                attachment_type = (request.attachment_type or "photo").lower()
                if attachment_type == "document":
                    sent_message = await bot.send_document(
                        chat_id=admin_id,
                        document=request.photo_file_id,
                        caption=request_info,
                        reply_markup=keyboard,
                    )
                else:
                    sent_message = await bot.send_photo(
                        chat_id=admin_id,
                        photo=request.photo_file_id,
                        caption=request_info,
                        reply_markup=keyboard,
                    )
            else:
                sent_message = await bot.send_message(chat_id=admin_id, text=request_info, reply_markup=keyboard)
            request.admin_message_id = sent_message.message_id
            db_session.commit()
            logger.info("Уведомление о заявке %s отправлено администратору %s.", request.id, admin_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось отправить уведомление администратору %s о заявке %s: %s", admin_id, request.id, exc)