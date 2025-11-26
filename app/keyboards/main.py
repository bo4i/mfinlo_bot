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
        keyboard.append([KeyboardButton(text="Новые заявки")])
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


def get_aho_issue_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="1. Заявка на канцтовары", callback_data="aho_issue_supplies")],
        [InlineKeyboardButton(text="2. Замена световых ламп", callback_data="aho_issue_lamps")],
        [InlineKeyboardButton(text="3. Починка кондиционера", callback_data="aho_issue_aircon")],
        [InlineKeyboardButton(text="4. Пользование авто", callback_data="aho_issue_car")],
        [InlineKeyboardButton(text="5. Заявка хозтовары", callback_data="aho_issue_household")],
        [InlineKeyboardButton(text="6. Регулировка отопления", callback_data="aho_issue_heating")],
        [InlineKeyboardButton(text="7. Заявка на мелкие ремонтные работы", callback_data="aho_issue_repairs")],
        [InlineKeyboardButton(text="8. Прочее", callback_data="aho_issue_other")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_aho_other_subcategory_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Уборка кабинета", callback_data="aho_other_cleaning")],
        [InlineKeyboardButton(text="Указать самостоятельно", callback_data="aho_other_custom")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_aho_issue")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_comment_skip_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_request_confirmation_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Подтвердить", callback_data="confirm_request")],
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_request")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)