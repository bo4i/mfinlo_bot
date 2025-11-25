from aiogram.fsm.state import State, StatesGroup


class NewRequestStates(StatesGroup):
    waiting_for_description = State()
    waiting_for_photo = State()
    waiting_for_urgency = State()
    waiting_for_date = State()
    waiting_for_time = State()
    request_type = State()