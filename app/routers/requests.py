import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db import get_db
from app.db.models import Admin, Request, User
from app.keyboards.admin import get_admin_new_request_keyboard
from app.keyboards.main import get_photo_skip_keyboard, get_urgency_keyboard
from app.states.requests import NewRequestStates

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text.in_({"Создать ИТ-заявку", "Создать АХО-заявку"}))
async def start_new_request(message: Message, state: FSMContext) -> None:
    with get_db() as db:
        user = db.query(User).filter(User.id == message.from_user.id).first()

        if not user or not user.registered:
            await message.answer("Вы не зарегистрированы или регистрация не завершена. Пожалуйста, начните с команды /start.")
            return

    request_type = "IT" if message.text == "Создать ИТ-заявку" else "AHO"
    await state.update_data(request_type=request_type)
    await message.answer(f"Опишите вашу проблему для {request_type}-заявки:")
    await state.set_state(NewRequestStates.waiting_for_description)


@router.message(NewRequestStates.waiting_for_description)
async def process_description(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите описание проблемы текстом.")
        return
    await state.update_data(description=message.text)
    await message.answer(
        "Прикрепите изображение проблемы (если это необходимо) или нажмите «Пропустить».",
        reply_markup=get_photo_skip_keyboard(),
    )
    await state.set_state(NewRequestStates.waiting_for_photo)


@router.message(NewRequestStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext) -> None:
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await message.answer("Изображение прикреплено. Как срочно необходимо выполнить заявку?", reply_markup=get_urgency_keyboard())
    await state.set_state(NewRequestStates.waiting_for_urgency)


@router.callback_query(NewRequestStates.waiting_for_photo, F.data == "skip_photo")
async def skip_photo(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer("Пропущено")
    await state.update_data(photo_file_id=None)
    await callback_query.message.answer("Как срочно необходимо выполнить заявку?", reply_markup=get_urgency_keyboard())
    await state.set_state(NewRequestStates.waiting_for_urgency)


@router.message(NewRequestStates.waiting_for_photo)
async def handle_unexpected_photo_input(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте фото или нажмите кнопку «Пропустить».")


@router.callback_query(NewRequestStates.waiting_for_urgency, F.data.in_({"urgency_asap", "urgency_date"}))
async def process_urgency_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    if callback_query.data == "urgency_asap":
        await state.update_data(urgency="ASAP")
        await save_request(callback_query.message, state, callback_query.from_user.id, bot=callback_query.bot)
    elif callback_query.data == "urgency_date":
        await state.update_data(urgency="DATE")
        await callback_query.message.answer("Укажите желаемую дату и время выполнения заявки (например, 2025-12-31 10:00):")
        await state.set_state(NewRequestStates.waiting_for_date)


@router.message(NewRequestStates.waiting_for_date)
async def process_date(message: Message, state: FSMContext) -> None:
    try:
        datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        await state.update_data(due_date=message.text)
        await save_request(message, state, message.from_user.id, bot=message.bot)
    except ValueError:
        await message.answer(
            "Неверный формат даты и времени. Пожалуйста, используйте формат ГГГГ-ММ-ДД ЧЧ:ММ (например, 2025-12-31 10:00).",
        )


async def save_request(message: Message, state: FSMContext, user_id: int, bot: Bot) -> None:
    user_data = await state.get_data()
    request_type = user_data.get("request_type")
    description = user_data.get("description")
    photo_file_id = user_data.get("photo_file_id")
    urgency = user_data.get("urgency")
    due_date = user_data.get("due_date") if urgency == "DATE" else None

    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            await message.answer("Произошла ошибка: пользователь не найден. Пожалуйста, попробуйте начать заново (/start).")
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
        )
        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        await message.answer("Ваша заявка успешно создана и будет рассмотрена.")
        await state.clear()
        await notify_admins(db, new_request, user, bot)
        logger.info("Заявка ID:%s от пользователя %s создана и отправлена администраторам.", new_request.id, user.id)


async def notify_admins(db_session, request: Request, user: User, bot: Bot) -> None:
    admin_type_filter = "IT_ADMIN" if request.request_type == "IT" else "AHO_ADMIN"
    admin_ids_to_notify = [admin.id for admin in db_session.query(Admin).filter(Admin.admin_type == admin_type_filter).all()]

    user_details = f"📞 Телефон: {user.phone_number}\n🏢 Организация: {user.organization}"
    if user.office_number:
        user_details += f"\n🚪 Кабинет: {user.office_number}"

    request_info = (
        f"🚨 Новая заявка ({request.request_type}) от {user.full_name} 🚨\n"
        f"{user_details}\n"
        f"📝 Описание: {request.description}\n"
        f"⏰ Срочность: {'Как можно скорее' if request.urgency == 'ASAP' else f'К {request.due_date}'}\n"
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