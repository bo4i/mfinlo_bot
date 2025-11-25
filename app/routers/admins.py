import logging
from datetime import datetime
from datetime import timedelta
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.db import get_db
from app.db.models import Request, User
from app.keyboards.admin import (
    get_admin_clarify_active_keyboard,
    get_admin_clarify_active_reply_keyboard,
    get_admin_done_keyboard,
    get_admin_new_request_keyboard,
    get_admin_post_clarification_keyboard,
)
from app.keyboards.user import get_user_clarify_active_reply_keyboard
from app.states.clarification import ClarificationState

logger = logging.getLogger(__name__)

router = Router()


async def finish_admin_clarification(
    *,
    state: FSMContext,
    bot: Bot,
    admin_chat_id: int,
    admin_id: int,
    request_id: int | None = None,
    current_message_id: int | None = None,
    current_message_text: str | None = None,
) -> None:
    state_data = await state.get_data()
    if request_id is None:
        request_id = state_data.get("request_id")

    target_user_id = state_data.get("target_user_id")

    if not request_id:
        await bot.send_message(
            chat_id=admin_chat_id,
            text="Заявка не найдена. Попробуйте начать диалог заново или используйте /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await bot.send_message(
                chat_id=admin_chat_id,
                text="Заявка не найдена.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

        request.status = "Принято"
        if request.assigned_admin_id == admin_id:
            request.assigned_admin_id = None
        db.commit()

        await state.clear()

        request_data = {
            "id": request.id,
            "description": request.description or "",
            "request_type": request.request_type,
            "urgency": request.urgency,
            "due_date": request.due_date,
            "status": request.status,
            "admin_message_id": request.admin_message_id,
            "user_id": request.user_id,
        }

        user_creator = db.query(User).filter(User.id == request.user_id).first()
        user_details = None
        if user_creator:
            user_details = f"📞 Телефон: {user_creator.phone_number}\n🏢 Организация: {user_creator.organization}"
            if user_creator.office_number:
                user_details += f"\n🚪 Кабинет: {user_creator.office_number}"
            user_full_name = user_creator.full_name
        else:
            user_full_name = "Неизвестный пользователь"

        urgency_text = (
            "Как можно скорее"
            if request_data["urgency"] == "ASAP"
            else f"К {request_data['due_date']}"
        )

        request_info = (
            f"🚨 Заявка ({request_data['request_type']}) от {user_full_name} 🚨\n"
            f"{user_details or 'Пользователь не найден'}\n"
            f"📝 Описание: {request_data['description']}\n"
            f"⏰ Срочность: {urgency_text}\n"
            f"🆔 Заявка ID: {request_data['id']}\n\n"
            f"✅ Статус: {request_data['status']}"
        )

    if target_user_id:
        user_state = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=target_user_id, user_id=target_user_id),
        )
        user_state_data = await user_state.get_data()
        current_user_state = await user_state.get_state()
        if current_user_state == ClarificationState.user_active_dialogue and user_state_data.get(
            "request_id"
        ) == request_id:
            await user_state.clear()
            try:
                await bot.send_message(
                    chat_id=target_user_id,
                    text=(
                        f"Диалог по заявке ID:{request_data['id']} ({request_data['description'][:50] if request_data else '...'}) "
                        "завершен администратором."
                    ),
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Не удалось уведомить пользователя %s о завершении диалога: %s",
                    target_user_id,
                    exc,
                )

    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text="Диалог уточнения завершен.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось отправить сообщение об окончании диалога администратору: %s", exc)

    if current_message_id and current_message_text:
        try:
            await bot.edit_message_text(
                chat_id=admin_chat_id,
                message_id=current_message_id,
                text=current_message_text,
                reply_markup=get_admin_post_clarification_keyboard(request_data["id"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Не удалось обновить сообщение администратора при завершении диалога: %s",
                exc,
            )
    else:
        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text="Диалог уточнения завершен. Выберите дальнейшее действие.",
                reply_markup=get_admin_post_clarification_keyboard(request_data["id"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось отправить сообщение администратора при завершении диалога: %s", exc)

    if request_data["admin_message_id"]:
        try:
            await bot.edit_message_text(
                chat_id=admin_chat_id,
                message_id=request_data["admin_message_id"],
                text=request_info,
                reply_markup=get_admin_post_clarification_keyboard(request_data["id"]),
            )
            logger.info(
                "Сообщение администратору для заявки %s обновлено после завершения диалога.", request_data["id"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Не удалось обновить сообщение администратору после завершения диалога для заявки %s: %s",
                request_data["id"],
                exc,
            )


@router.callback_query(F.data.startswith("admin_accept_"))
async def admin_accept_request(callback_query: CallbackQuery, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[2])
    admin_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()
        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

        if request.status != "Принято":
            await callback_query.message.answer(f"Эта заявка уже имеет статус: {request.status}.")
            return

        request.status = "Принято к исполнению"
        request.assigned_admin_id = admin_id
        admin_user = db.query(User).filter(User.id == admin_id).first()
        admin_full_name = admin_user.full_name if admin_user else "Администратор"
        request_user_id = request.user_id
        request_description = request.description or ""
        db.commit()
        logger.info("Заявка ID:%s принята к исполнению администратором %s.", request.id, admin_id)

    try:
        await callback_query.message.edit_text(
            f"{callback_query.message.text}\n\n✅ Статус: Принято к исполнению ({admin_full_name})",
            reply_markup=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось обновить сообщение администратору для заявки %s: %s", request_id, exc)

    user_full_name = admin_full_name if admin_full_name else "Неизвестный администратор"
    try:
        await bot.send_message(
            chat_id=request_user_id,
            text=(
                f"Ваша заявка ID:{request_id} ({request_description[:50]}...) принята к исполнению.\n"
                f"Исполнитель: {user_full_name}."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось уведомить пользователя %s о принятии заявки %s: %s", request_user_id, request_id, exc)


@router.callback_query(F.data.startswith("admin_decline_"))
async def admin_decline_request(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[2])
    admin_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

        if request.assigned_admin_id == admin_id:
            request.assigned_admin_id = None

        if request.status != "Принято":
            request.status = "Принято"

        db.commit()
        logger.info("Администратор %s отказался от заявки %s после уточнения.", admin_id, request.id)

    try:
        await callback_query.message.delete()
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось удалить сообщение администратора при отказе: %s", exc)


@router.callback_query(F.data.startswith("admin_clarify_start_"))
async def admin_clarify_start(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[3])
    admin_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

        if request.status == "Выполнено":
            await callback_query.message.answer("Эта заявка уже выполнена.")
            return

        await state.update_data(
            target_user_id=request.user_id,
            request_id=request_id,
            original_admin_message_id=callback_query.message.message_id,
        )
        await state.set_state(ClarificationState.admin_active_dialogue)

        user_state = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=request.user_id, user_id=request.user_id),
        )
        await user_state.update_data(target_admin_id=admin_id, request_id=request_id)
        await user_state.set_state(ClarificationState.user_active_dialogue)

        if not request.assigned_admin_id:
            request.assigned_admin_id = admin_id
        request.status = "Уточнение"
        db.commit()
        logger.info("Администратор %s начал уточнение для заявки %s. Статус: Уточнение.", admin_id, request.id)

        try:
            await bot.send_message(
                chat_id=request.user_id,
                text=(
                    f"Администратор начал диалог по вашей заявке ID:{request.id} ({request.description[:50]}...).\n"
                    "Вы можете отправлять сообщения в ответ."
                ),
                reply_markup=get_user_clarify_active_reply_keyboard(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось уведомить пользователя %s о начале диалога уточнения: %s", request.user_id, exc)

    await callback_query.message.answer(
        "Вы начали диалог уточнения с пользователем. Отправляйте сообщения. Для завершения диалога нажмите кнопку:",
        reply_markup=get_admin_clarify_active_reply_keyboard(),
    )


@router.message(StateFilter(ClarificationState.admin_active_dialogue))
async def process_admin_clarification_message(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    if message.text == "Завершить уточнение":
        await finish_admin_clarification(
            state=state,
            bot=bot,
            admin_chat_id=message.chat.id,
            admin_id=message.from_user.id,
        )
        return

    state_data = await state.get_data()
    target_user_id = state_data.get("target_user_id")
    request_id = state_data.get("request_id")

    if not target_user_id or not request_id:
        await message.answer("Произошла ошибка в диалоге уточнения. Пожалуйста, попробуйте начать снова или используйте /start.")
        await state.clear()
        return

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        try:
            await bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"💬 От администратора по заявке ID:{request.id} ({request.description[:50] if request else '...'})\n\n"
                    f"{message.text}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            await message.answer("Не удалось отправить сообщение пользователю. Возможно, он заблокировал бота.")
            logger.error(
                "Не удалось отправить сообщение пользователю %s для заявки %s: %s",
                target_user_id,
                request_id,
                exc,
            )


@router.callback_query(F.data.startswith("admin_clarify_end_"))
async def admin_clarify_end(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[3])

    await finish_admin_clarification(
        state=state,
        bot=bot,
        admin_chat_id=callback_query.message.chat.id,
        admin_id=callback_query.from_user.id,
        request_id=request_id,
        current_message_id=callback_query.message.message_id,
        current_message_text=callback_query.message.text,
    )


@router.message(StateFilter(ClarificationState.admin_active_dialogue), F.text == "Завершить уточнение")
async def admin_clarify_end_message(message: Message, state: FSMContext, bot: Bot) -> None:
    await finish_admin_clarification(
        state=state,
        bot=bot,
        admin_chat_id=message.chat.id,
        admin_id=message.from_user.id,
    )


@router.message(F.text == "Мои принятые заявки")
async def show_assigned_requests(message: Message) -> None:
    admin_id = message.from_user.id
    with get_db() as db:
        admin_user = db.query(User).filter(User.id == admin_id).first()

        if not admin_user or admin_user.role not in ["it_admin", "aho_admin"]:
            await message.answer("У вас нет доступа к этой функции.")
            return

        two_days_ago = datetime.now() - timedelta(days=2)

        requests = (
            db.query(Request)
            .filter(
                Request.assigned_admin_id == admin_id,
                (Request.status != "Выполнено") | (Request.completed_at >= two_days_ago),
            )
            .order_by(Request.created_at.desc())
            .all()
        )

        if not requests:
            await message.answer(
                "У вас пока нет принятых к исполнению заявок или недавно выполненных."
            )
            return

    for req in requests:
        user = db.query(User).filter(User.id == req.user_id).first()
        user_details = (
            f"📞 Телефон: {user.phone_number}\n🏢 Организация: {user.organization}"
            if user
            else "Пользователь не найден"
        )
        if user and user.office_number:
            user_details += f"\n🚪 Кабинет: {user.office_number}"

        keyboard_to_show = None
        if req.status == "Принято":
            keyboard_to_show = get_admin_new_request_keyboard(req.id)
        elif req.status == "Принято к исполнению":
            keyboard_to_show = get_admin_done_keyboard(req.id)
        elif req.status == "Уточнение":
            keyboard_to_show = get_admin_clarify_active_keyboard(req.id)

        request_text = (
            f"🚨 Заявка ({req.request_type}) от {user.full_name if user else 'Неизвестный пользователь'} 🚨\n"
            f"{user_details}\n"
            f"📝 Описание: {req.description}\n"
            f"⏰ Срочность: {'Как можно скорее' if req.urgency == 'ASAP' else f'К {req.due_date}'}\n"
            f"🆔 Заявка ID: {req.id}\n\n"
            f"✅ Статус: {req.status}"
        )
        await message.answer(request_text, reply_markup=keyboard_to_show)


@router.callback_query(F.data.startswith("admin_done_"))
async def admin_done_request(callback_query: CallbackQuery, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[2])
    admin_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

        if request.assigned_admin_id != admin_id:
            await callback_query.message.answer("Вы не являетесь исполнителем этой заявки.")
            return

        if request.status == "Выполнено":
            await callback_query.message.answer("Эта заявка уже отмечена как выполненная.")
            return

        request.status = "Выполнено"
        request.completed_at = datetime.now()
        db.commit()
        logger.info("Заявка ID:%s отмечена как 'Выполнено' администратором %s.", request.id, admin_id)

        try:
            await callback_query.message.edit_text(
                f"{callback_query.message.text}\n\n✅ Статус: Выполнено",
                reply_markup=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось обновить сообщение администратору для заявки %s: %s", request.id, exc)

        try:
            await bot.send_message(
                chat_id=request.user_id,
                text=f"🎉 Ваша заявка ID:{request.id} ({request.description[:50]}...) исполнена!",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось уведомить пользователя %s о выполнении заявки %s: %s", request.user_id, request.id, exc)