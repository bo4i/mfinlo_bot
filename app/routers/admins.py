import logging
from datetime import datetime
from datetime import timedelta
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message

from app.db import get_db
from app.db.models import Request, User
from app.keyboards.admin import (
    get_admin_clarify_active_keyboard,
    get_admin_done_keyboard,
    get_admin_new_request_keyboard,
)
from app.states.clarification import ClarificationState

logger = logging.getLogger(__name__)

router = Router()


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
    db.commit()
    logger.info("Заявка ID:%s принята к исполнению администратором %s.", request.id, admin_id)

    try:
        await callback_query.message.edit_text(
            f"{callback_query.message.text}\n\n✅ Статус: Принято к исполнению ({admin_user.full_name if admin_user else 'Администратор'})",
            reply_markup=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось обновить сообщение администратору для заявки %s: %s", request.id, exc)

    user_full_name = admin_user.full_name if admin_user else "Неизвестный администратор"
    try:
        await bot.send_message(
            chat_id=request.user_id,
            text=(
                f"Ваша заявка ID:{request.id} ({request.description[:50]}...) принята к исполнению.\n"
                f"Исполнитель: {user_full_name}."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось уведомить пользователя %s о принятии заявки %s: %s", request.user_id, request.id, exc)


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
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось уведомить пользователя %s о начале диалога уточнения: %s", request.user_id, exc)

    await callback_query.message.answer(
        "Вы начали диалог уточнения с пользователем. Отправляйте сообщения. Для завершения диалога нажмите кнопку:",
        reply_markup=get_admin_clarify_active_keyboard(request_id),
    )


@router.message(StateFilter(ClarificationState.admin_active_dialogue))
async def process_admin_clarification_message(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
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
    admin_id = callback_query.from_user.id

    state_data = await state.get_data()
    target_user_id = state_data.get("target_user_id")
    original_admin_message_id = state_data.get("original_admin_message_id")

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

        request.status = "Принято к исполнению"
        request.assigned_admin_id = request.assigned_admin_id or admin_id
        db.commit()

        await state.clear()

    if target_user_id:
        user_state = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=target_user_id, user_id=target_user_id),
        )
        user_state_data = await user_state.get_data()
        current_user_state = await user_state.get_state()
        if current_user_state == ClarificationState.user_active_dialogue and user_state_data.get(
                "request_id") == request_id:
            await user_state.clear()
            try:
                await bot.send_message(
                    chat_id=target_user_id,
                    text=(
                        f"Диалог по заявке ID:{request.id} ({request.description[:50] if request else '...'}) завершен администратором."
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось уведомить пользователя %s о завершении диалога: %s", target_user_id, exc)

    if original_admin_message_id:
        try:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=original_admin_message_id,
                text=callback_query.message.text,
                reply_markup=get_admin_done_keyboard(request.id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Не удалось обновить сообщение администратору после завершения диалога для заявки %s: %s",
                request.id,
                exc,
            )

    try:
        await callback_query.message.edit_text("Диалог уточнения завершен. Статус заявки: Принято к исполнению")
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось обновить сообщение администратора при завершении диалога: %s", exc)

    user_creator = db.query(User).filter(User.id == request.user_id).first()
    user_details = f"📞 Телефон: {user_creator.phone_number}\n🏢 Организация: {user_creator.organization}"
    if user_creator and user_creator.office_number:
        user_details += f"\n🚪 Кабинет: {user_creator.office_number}"

    request_info = (
        f"🚨 Заявка ({request.request_type}) от {user_creator.full_name} 🚨\n"
        f"{user_details}\n"
        f"📝 Описание: {request.description}\n"
        f"⏰ Срочность: {'Как можно скорее' if request.urgency == 'ASAP' else f'К {request.due_date}'}\n"
        f"🆔 Заявка ID: {request.id}\n\n"
        f"✅ Статус: {request.status}"
    )

    if request.admin_message_id:
        try:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=request.admin_message_id,
                text=request_info,
                reply_markup=get_admin_done_keyboard(request.id),
            )
            logger.info("Сообщение администратору для заявки %s обновлено после завершения диалога.", request.id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Не удалось обновить сообщение администратору после завершения диалога для заявки %s: %s",
                request.id,
                exc,
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
        user_info = (
            f"{user.full_name}, {user.organization}, {user.phone_number}"
            if user
            else "Неизвестный пользователь"
        )
        if user and user.office_number:
            user_info += f", каб. {user.office_number}"

        request_text = (
            f"--- Заявка ID: {req.id} ({req.request_type}) ---\n"
            f"От: {user_info}\n"
            f"Описание: {req.description}\n"
            f"Срочность: {'Как можно скорее' if req.urgency == 'ASAP' else f'К {req.due_date}'}\n"
            f"Статус: {req.status}"
        )

        keyboard_to_show = None
        if req.status == "Принято":
            keyboard_to_show = get_admin_new_request_keyboard(req.id)
        elif req.status == "Принято к исполнению":
            keyboard_to_show = get_admin_done_keyboard(req.id)
        elif req.status == "Уточнение":
            keyboard_to_show = get_admin_clarify_active_keyboard(req.id)

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