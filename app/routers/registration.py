import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from app.config import ORGANIZATIONS_NEEDING_OFFICE_NUMBER, PREDEFINED_ORGANIZATIONS
from app.db import get_db
from app.db.models import User
from app.keyboards.main import (
    get_main_menu_keyboard,
    get_organization_selection_keyboard,
)
from app.states.registration import RegistrationStates

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    with get_db() as db:
        user = db.query(User).filter(User.id == message.from_user.id).first()

        if not user:
            new_user = User(id=message.from_user.id)
            db.add(new_user)
            try:
                db.commit()
                db.refresh(new_user)
                logger.info("Новый пользователь %s добавлен в БД.", message.from_user.id)
            except IntegrityError:
                db.rollback()
                logger.warning(
                    "Пользователь %s уже существует, но не был найден в начале сессии. Продолжаем.",
                    message.from_user.id,
                )
                user = db.query(User).filter(User.id == message.from_user.id).first()
                if not user:
                    await message.answer("Произошла ошибка при инициализации пользователя. Попробуйте еще раз.")
                    return

            await message.answer("Добро пожаловать! Для использования бота необходимо зарегистрироваться. Укажите ваше ФИО:")
            await state.set_state(RegistrationStates.waiting_for_full_name)
        elif not user.registered:
            await message.answer("Вы не завершили регистрацию. Пожалуйста, укажите ваше ФИО:")
            await state.set_state(RegistrationStates.waiting_for_full_name)
        else:
            await message.answer("С возвращением! Главное меню:", reply_markup=get_main_menu_keyboard(user.role))
            await state.clear()


@router.message(RegistrationStates.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ваше ФИО текстом.")
        return
    await state.update_data(full_name=message.text)
    await message.answer("Отлично! Теперь укажите ваш номер телефона:")
    await state.set_state(RegistrationStates.waiting_for_phone_number)


@router.message(RegistrationStates.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите ваш номер телефона текстом.")
        return
    await state.update_data(phone_number=message.text)
    try:
        await message.answer(
            "Пожалуйста, выберите вашу организацию из списка или введите название самостоятельно:",
            reply_markup=get_organization_selection_keyboard(),
        )
        await state.set_state(RegistrationStates.waiting_for_organization_choice)
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка при отправке клавиатуры выбора организации: %s", exc)
        await message.answer("Произошла ошибка при запросе организации. Пожалуйста, попробуйте еще раз.")
        await state.clear()


@router.callback_query(RegistrationStates.waiting_for_organization_choice, F.data.startswith("org_idx_"))
async def process_organization_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    org_index = int(callback_query.data.split("_")[2])

    if 0 <= org_index < len(PREDEFINED_ORGANIZATIONS):
        organization_name = PREDEFINED_ORGANIZATIONS[org_index]
        await state.update_data(organization=organization_name)

        try:
            await callback_query.message.edit_text(f"Вы выбрали: {organization_name}")

            if organization_name in ORGANIZATIONS_NEEDING_OFFICE_NUMBER:
                await callback_query.message.answer("Пожалуйста, укажите номер кабинета:")
                await state.set_state(RegistrationStates.waiting_for_office_number)
            else:
                await complete_registration(callback_query.message, state)
        except Exception as exc:  # noqa: BLE001
            logger.error("Ошибка при редактировании сообщения после выбора организации: %s", exc)
            await callback_query.message.answer(
                "Произошла ошибка при обработке выбора организации. Пожалуйста, попробуйте еще раз.",
            )
            await state.clear()
    else:
        await callback_query.message.answer("Произошла ошибка при выборе организации. Пожалуйста, попробуйте снова.")
        await state.clear()


@router.callback_query(RegistrationStates.waiting_for_organization_choice, F.data == "org_other")
async def process_other_organization_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    try:
        await callback_query.message.edit_text("Пожалуйста, введите название вашей организации вручную:")
        await state.set_state(RegistrationStates.waiting_for_manual_organization_input)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Ошибка при редактировании сообщения после выбора 'Указать название самостоятельно': %s",
            exc,
        )
        await callback_query.message.answer(
            "Произошла ошибка при запросе ручного ввода организации. Пожалуйста, попробуйте еще раз.",
        )
        await state.clear()


@router.message(RegistrationStates.waiting_for_manual_organization_input)
async def process_manual_organization_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите название вашей организации текстом.")
        return

    organization_name = message.text.strip()
    await state.update_data(organization=organization_name)
    await complete_registration(message, state)


@router.message(RegistrationStates.waiting_for_office_number)
async def process_office_number(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введите номер кабинета текстом.")
        return
    await state.update_data(office_number=message.text)
    await complete_registration(message, state)


async def complete_registration(message: Message, state: FSMContext) -> None:
    user_data = await state.get_data()
    with get_db() as db:
        user = db.query(User).filter(User.id == message.from_user.id).first()

        if user:
            user.full_name = user_data.get("full_name")
            user.phone_number = user_data.get("phone_number")
            user.organization = user_data.get("organization")
            user.office_number = user_data.get("office_number") if "office_number" in user_data else None
            user.registered = True
            db.commit()
            logger.info("Пользователь %s успешно зарегистрирован.", user.id)
            await message.answer(
                "Регистрация завершена! Теперь вы можете создавать заявки.",
                reply_markup=get_main_menu_keyboard(user.role),
            )
            await state.clear()
        else:
            await message.answer("Произошла ошибка при сохранении данных. Пожалуйста, попробуйте начать регистрацию заново (/start).")
            await state.clear()