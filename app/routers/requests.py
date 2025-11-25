import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

from app.db import get_db
from app.db.models import Admin, Request, User
from app.keyboards.admin import get_admin_new_request_keyboard
from app.keyboards.main import (
    get_aho_issue_keyboard,
    get_comment_skip_keyboard,
    get_photo_skip_keyboard,
    get_urgency_keyboard,
)
from app.states.requests import NewRequestStates

logger = logging.getLogger(__name__)

router = Router()


async def update_request_prompt(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup=None,
) -> int:
    """Edit an existing prompt message or send a new one if editing fails."""
    if message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            return message_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отредактировать сообщение %s: %s", message_id, exc)

    sent_message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    return sent_message.message_id


async def _prompt_for_photo(
    bot: Bot,
    chat_id: int,
    prompt_message_id: int | None,
    state: FSMContext,
    description: str,
) -> None:
    prompt_message_id = await update_request_prompt(
        bot=bot,
        chat_id=chat_id,
        message_id=prompt_message_id,
        text="Прикрепите изображение проблемы (если это необходимо) или нажмите «Пропустить».",
        reply_markup=get_photo_skip_keyboard(),
    )
    await state.update_data(description=description, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_photo)


async def _prompt_for_comment(bot: Bot, chat_id: int, prompt_message_id: int | None, state: FSMContext) -> None:
    prompt_message_id = await update_request_prompt(
        bot=bot,
        chat_id=chat_id,
        message_id=prompt_message_id,
        text="Вы можете добавить дополнительный комментарий к заявке или нажмите «Пропустить».",
        reply_markup=get_comment_skip_keyboard(),
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_comment)



@router.message(F.text.in_({"Создать ИТ-заявку", "Создать АХО-заявку"}))
async def start_new_request(message: Message, state: FSMContext) -> None:
    with get_db() as db:
        user = db.query(User).filter(User.id == message.from_user.id).first()

        if not user or not user.registered:
            await message.answer("Вы не зарегистрированы или регистрация не завершена. Пожалуйста, начните с команды /start.")
            return

    request_type = "IT" if message.text == "Создать ИТ-заявку" else "AHO"
    await state.update_data(request_type=request_type)

    if request_type == "AHO":
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=None,
            text="Выберите тип проблемы для АХО-заявки:",
            reply_markup=get_aho_issue_keyboard(),
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.choosing_aho_issue)
        return

    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=None,
        text=f"Опишите вашу проблему для {request_type}-заявки:",
    )
    await state.update_data(prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_description)

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
    }

    if selection == "other":
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Опишите проблему для АХО-заявки:",
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_description)
        return

    if selection == "car":
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Для заявки на пользование авто укажите дату, время начала и продолжительность выезда.",
        )
        await state.update_data(description=issue_descriptions.get(selection, ""), prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_car_details)
        return

    description = issue_descriptions.get(selection)
    if not description:
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Не удалось определить выбранный тип заявки. Пожалуйста, попробуйте снова.",
            reply_markup=get_aho_issue_keyboard(),
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    await _prompt_for_photo(callback_query.bot, callback_query.message.chat.id, prompt_message_id, state, description)


@router.message(NewRequestStates.waiting_for_description)
async def process_description(message: Message, state: FSMContext) -> None:
    if not message.text:
        user_data = await state.get_data()
        prompt_message_id = user_data.get("prompt_message_id")
        await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Пожалуйста, введите описание проблемы текстом.",
        )
        return

    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    await _prompt_for_photo(message.bot, message.chat.id, prompt_message_id, state, message.text)


@router.message(NewRequestStates.waiting_for_car_details)
async def process_car_details(message: Message, state: FSMContext) -> None:
    details_text = (message.text or "").strip()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    base_description = user_data.get("description", "Пользование авто")

    if not details_text:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Пожалуйста, укажите дату, время начала и продолжительность выезда для заявки на авто.",
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        return

    description = f"{base_description}. {details_text}"
    await _prompt_for_photo(message.bot, message.chat.id, prompt_message_id, state, description)


@router.message(NewRequestStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext) -> None:
    photo_file_id = message.photo[-1].file_id
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=message.bot,
        chat_id=message.chat.id,
        message_id=prompt_message_id,
        text="Изображение прикреплено. Как срочно необходимо выполнить заявку?",
        reply_markup=get_urgency_keyboard(),
    )
    await state.update_data(photo_file_id=photo_file_id, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_urgency)


@router.callback_query(NewRequestStates.waiting_for_photo, F.data == "skip_photo")
async def skip_photo(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Пропущено")
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    prompt_message_id = await update_request_prompt(
        bot=callback_query.bot,
        chat_id=callback_query.message.chat.id,
        message_id=prompt_message_id,
        text="Как срочно необходимо выполнить заявку?",
        reply_markup=get_urgency_keyboard(),
    )
    await state.update_data(photo_file_id=None, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_urgency)


@router.message(NewRequestStates.waiting_for_photo)
async def handle_unexpected_photo_input(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте фото или нажмите кнопку «Пропустить».")


@router.callback_query(NewRequestStates.waiting_for_urgency, F.data.in_({"urgency_asap", "urgency_date"}))
async def process_urgency_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    user_data = await state.get_data()
    prompt_message_id = user_data.get("prompt_message_id")
    if callback_query.data == "urgency_asap":
        await state.update_data(urgency="ASAP")
        await _prompt_for_comment(callback_query.bot, callback_query.message.chat.id, prompt_message_id, state)
    elif callback_query.data == "urgency_date":
        await state.update_data(urgency="DATE")
        calendar_markup = await SimpleCalendar().start_calendar()
        prompt_message_id = await update_request_prompt(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            message_id=prompt_message_id,
            text="Выберите желаемую дату выполнения заявки:",
            reply_markup=calendar_markup,
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
    )
    await state.update_data(selected_date=formatted_date, prompt_message_id=prompt_message_id)
    await state.set_state(NewRequestStates.waiting_for_time)


@router.message(NewRequestStates.waiting_for_time)
async def process_time(message: Message, state: FSMContext) -> None:
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
        )
        await state.update_data(prompt_message_id=prompt_message_id)
        await state.set_state(NewRequestStates.waiting_for_urgency)
        return

    try:
        parsed_datetime = datetime.strptime(f"{selected_date} {time_text}", "%Y-%m-%d %H:%M")
        normalized_date = parsed_datetime.strftime("%Y-%m-%d %H:%M")
        await state.update_data(due_date=normalized_date, prompt_message_id=prompt_message_id)
        await _prompt_for_comment(message.bot, message.chat.id, prompt_message_id, state)
    except ValueError:
        prompt_message_id = await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (например, 10:00).",
        )
        await state.update_data(prompt_message_id=prompt_message_id)


@router.message(NewRequestStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        user_data = await state.get_data()
        prompt_message_id = user_data.get("prompt_message_id")
        await update_request_prompt(
            bot=message.bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Комментарий должен быть текстом. Введите комментарий или нажмите «Пропустить».",
            reply_markup=get_comment_skip_keyboard(),
        )
        return

    await state.update_data(comment=message.text)
    await save_request(message, state, message.from_user.id, bot=message.bot)


@router.callback_query(NewRequestStates.waiting_for_comment, F.data == "skip_comment")
async def skip_comment(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Пропущено")
    await state.update_data(comment=None)
    await save_request(callback_query.message, state, callback_query.from_user.id, bot=callback_query.bot)


async def save_request(message: Message, state: FSMContext, user_id: int, bot: Bot) -> None:
    user_data = await state.get_data()
    request_type = user_data.get("request_type")
    description = user_data.get("description")
    photo_file_id = user_data.get("photo_file_id")
    urgency = user_data.get("urgency")
    due_date = user_data.get("due_date") if urgency == "DATE" else None
    prompt_message_id = user_data.get("prompt_message_id")
    comment = user_data.get("comment")

    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            await update_request_prompt(
                bot=bot,
                chat_id=message.chat.id,
                message_id=prompt_message_id,
                text="Произошла ошибка: пользователь не найден. Пожалуйста, попробуйте начать заново (/start).",
            )
            await state.clear()
            return

        new_request = Request(
            user_id=user_id,
            request_type=request_type,
            description=description,
            photo_file_id=photo_file_id,
            urgency=urgency,
            due_date=due_date,
            status="Принято",
            comment=comment,
        )
        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        await update_request_prompt(
            bot=bot,
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text="Ваша заявка успешно создана и будет рассмотрена.",
        )
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

    request_info = (
        f"🚨 Новая заявка ({request.request_type}) от {user.full_name} 🚨\n"
        f"{user_details}\n"
        f"📝 Описание: {request.description}\n"
        f"⏰ Срочность: {'Как можно скорее' if request.urgency == 'ASAP' else f'К {request.due_date}'}{comment_block}\n"
        f"🆔 Заявка ID: {request.id}"
    )

    keyboard = get_admin_new_request_keyboard(request.id)

    for admin_id in admin_ids_to_notify:
        try:
            if request.photo_file_id:
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