from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_admin_new_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Принять", callback_data=f"admin_accept_{request_id}")],
        [InlineKeyboardButton(text="Отправить уточнение", callback_data=f"admin_clarify_start_{request_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_done_keyboard(request_id: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Выполнено", callback_data=f"admin_done_{request_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_clarify_active_keyboard(request_id: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Завершить уточнение", callback_data=f"admin_clarify_end_{request_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_post_clarification_keyboard(request_id: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Принять", callback_data=f"admin_accept_{request_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)