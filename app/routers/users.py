import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message

from app.db import get_db
from app.db.models import Request, User
from app.keyboards.user import get_user_clarify_active_keyboard, get_user_request_actions_keyboard
from app.states.clarification import ClarificationState

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text == "Мои заявки")
async def show_user_requests(message: Message) -> None:
    user_id = message.from_user.id
    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()

        if not user or not user.registered:
            await message.answer("Вы не зарегистрированы или регистрация не завершена. Пожалуйста, начните с команды /start.")
            return

        two_days_ago = datetime.now() - timedelta(days=2)

        requests = (
            db.query(Request)
            .filter(
                Request.user_id == user_id,
                (Request.status != "Выполнено") | (Request.completed_at >= two_days_ago),
            )
            .order_by(Request.created_at.desc())
            .all()
    )

        if not requests:
            await message.answer("У вас пока нет созданных заявок.")
            return

        for req in requests:
            admin_info = ""
            if req.assigned_admin_id:
                admin_user = db.query(User).filter(User.id == req.assigned_admin_id).first()
                if admin_user:
                    admin_info = f"Исполнитель: {admin_user.full_name}\n"

            response_text = (
                f"--- Заявка ID: {req.id} ({req.request_type}) ---\n"
                f"Описание: {req.description}\n"
                f"Срочность: {'Как можно скорее' if req.urgency == 'ASAP' else f'К {req.due_date}'}\n"
                f"Статус: {req.status}\n"
                f"{admin_info}"
                f"Создана: {req.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
            if req.status == "Выполнено" and req.completed_at:
                response_text += f"Выполнена: {req.completed_at.strftime('%Y-%m-%d %H:%M')}\n"

            if req.status != "Выполнено" or (
                    req.status == "Выполнено" and req.completed_at and req.completed_at >= two_days_ago
            ):
                await message.answer(response_text, reply_markup=get_user_request_actions_keyboard(req.id, req.status))
            else:
                await message.answer(response_text)


@router.callback_query(F.data.startswith("user_done_"))
async def user_mark_done_request(callback_query: CallbackQuery, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[2])
    user_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id, Request.user_id == user_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена или вы не являетесь ее создателем.")
            return

        if request.status == "Выполнено":
            await callback_query.message.answer("Эта заявка уже отмечена как выполненная.")
            return

        request.status = "Выполнено"
        request.completed_at = datetime.now()
        db.commit()
        logger.info("Заявка ID:%s отмечена пользователем %s как 'Выполнено'.", request.id, user_id)

        try:
            await callback_query.message.edit_text(
                f"{callback_query.message.text}\n\n✅ Статус: Выполнено",
                reply_markup=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось обновить сообщение пользователя для заявки %s: %s", request.id, exc)

        if request.assigned_admin_id:
            try:
                admin_user = db.query(User).filter(User.id == request.assigned_admin_id).first()
                if admin_user:
                    await bot.send_message(
                        chat_id=request.assigned_admin_id,
                        text=f"🎉 Пользователь {request.creator.full_name} отметил заявку ID:{request.id} как выполненную!",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Не удалось уведомить администратора %s о выполнении заявки %s пользователем: %s",
                    request.assigned_admin_id,
                    request.id,
                    exc,
                )


@router.callback_query(F.data.startswith("user_clarify_start_"))
async def user_clarify_start(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[3])
    user_id = callback_query.from_user.id

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id, Request.user_id == user_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена или вы не являетесь ее создателем.")
            return

        if not request.assigned_admin_id:
            await callback_query.message.answer("Эта заявка еще не принята администратором. Уточнение невозможно.")
            return

        await state.update_data(
            target_admin_id=request.assigned_admin_id,
            request_id=request_id,
            original_user_message_id=callback_query.message.message_id,
        )
        await state.set_state(ClarificationState.user_active_dialogue)

        admin_state = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=request.assigned_admin_id, user_id=request.assigned_admin_id),
        )
        await admin_state.update_data(target_user_id=user_id, request_id=request_id)
        await admin_state.set_state(ClarificationState.admin_active_dialogue)

        try:
            await bot.send_message(
                chat_id=request.assigned_admin_id,
                text=(
                    f"Пользователь {request.creator.full_name} начал диалог по заявке ID:{request.id}"
                    f" ({request.description[:50] if request else '...'}).\n"
                    "Вы можете отправлять сообщения в ответ."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Не удалось уведомить администратора %s о начале диалога уточнения: %s", request.assigned_admin_id, exc)

    await callback_query.message.answer(
        "Вы начали диалог уточнения с администратором. Отправляйте сообщения. Для завершения диалога нажмите кнопку:",
        reply_markup=get_user_clarify_active_keyboard(request_id),
    )


@router.message(StateFilter(ClarificationState.user_active_dialogue))
async def process_user_clarification_message(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    state_data = await state.get_data()
    target_admin_id = state_data.get("target_admin_id")
    request_id = state_data.get("request_id")

    if not target_admin_id or not request_id:
        await message.answer("Произошла ошибка в диалоге уточнения. Пожалуйста, попробуйте начать снова или используйте /start.")
        await state.clear()
        return

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()
        user = db.query(User).filter(User.id == message.from_user.id).first()

    try:
        await bot.send_message(
            chat_id=target_admin_id,
            text=(
                f"💬 От пользователя {user.full_name if user else message.from_user.id}"
                f" по заявке ID:{request.id} ({request.description[:50] if request else '...'})\n\n"
                f"{message.text}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer("Не удалось отправить сообщение администратору. Возможно, он заблокировал бота.")
        logger.error(
            "Не удалось отправить сообщение администратору %s для заявки %s: %s",
            target_admin_id,
            request_id,
            exc,
        )


@router.callback_query(F.data.startswith("user_clarify_end_"))
async def user_clarify_end(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    request_id = int(callback_query.data.split("_")[3])

    state_data = await state.get_data()
    target_admin_id = state_data.get("target_admin_id")
    original_user_message_id = state_data.get("original_user_message_id")

    with get_db() as db:
        request = db.query(Request).filter(Request.id == request_id).first()

        if not request:
            await callback_query.message.answer("Заявка не найдена.")
            return

    await state.clear()
    await callback_query.message.answer("Диалог уточнения завершен.")

    if target_admin_id:
        admin_state = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=target_admin_id, user_id=target_admin_id),
        )
        admin_state_data = await admin_state.get_data()
        current_admin_state = await admin_state.get_state()
        if current_admin_state == ClarificationState.admin_active_dialogue and admin_state_data.get("request_id") == request_id:
            await admin_state.clear()
            logger.info("Состояние администратора %s очищено после завершения диалога пользователем.", target_admin_id)
            try:
                await bot.send_message(
                    chat_id=target_admin_id,
                    text=(
                        f"Диалог по заявке ID:{request.id} ({request.description[:50] if request else '...'}) завершен пользователем."
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось уведомить администратора %s о завершении диалога: %s", target_admin_id, exc)

    if original_user_message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=original_user_message_id,
                reply_markup=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Не удалось обновить сообщение пользователя после завершения диалога для заявки %s: %s",
                request.id,
                exc,
            )