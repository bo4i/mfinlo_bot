from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def get_user_request_actions_keyboard(request_id: int, status: str) -> InlineKeyboardMarkup:
    buttons = []
    if status != "Выполнено":
        buttons.append([InlineKeyboardButton(text="Отметить как выполнено", callback_data=f"user_done_{request_id}")])
    buttons.append([InlineKeyboardButton(text="Задать уточнение", callback_data=f"user_clarify_start_{request_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_clarify_active_keyboard(request_id: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Завершить уточнение", callback_data=f"user_clarify_end_{request_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_clarify_active_reply_keyboard() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="Завершить уточнение")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)