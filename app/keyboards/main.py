from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.config import PREDEFINED_ORGANIZATIONS


def get_main_menu_keyboard(user_role: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Создать ИТ-заявку"), KeyboardButton(text="Создать АХО-заявку")],
        [KeyboardButton(text="Портал бюджетной системы Липецкой области", url="https://ufin48.ru/")],
    ]
    if user_role == "user":
        keyboard.append([KeyboardButton(text="Мои заявки")])
    elif user_role in ["it_admin", "aho_admin"]:
        keyboard.append(
            [KeyboardButton(text="Мои заявки"), KeyboardButton(text="Мои принятые заявки")]
        )
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_urgency_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Как можно скорее", callback_data="urgency_asap")],
        [InlineKeyboardButton(text="Указать дату", callback_data="urgency_date")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_photo_skip_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_photo")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_organization_selection_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for i, org in enumerate(PREDEFINED_ORGANIZATIONS):
        buttons.append([InlineKeyboardButton(text=org, callback_data=f"org_idx_{i}")])
    buttons.append([InlineKeyboardButton(text="Указать название самостоятельно", callback_data="org_other")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)