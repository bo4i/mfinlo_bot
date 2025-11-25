from aiogram.fsm.state import State, StatesGroup


class NewRequestStates(StatesGroup):
    choosing_aho_issue = State()
    waiting_for_description = State()
    waiting_for_car_details = State()
    waiting_for_photo = State()
    waiting_for_urgency = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_comment = State()