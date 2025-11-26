from aiogram.fsm.state import State, StatesGroup


class NewRequestStates(StatesGroup):
    choosing_category = State()
    choosing_subcategory = State()
    choosing_aho_category = State()
    choosing_aho_subcategory = State()
    waiting_for_description = State()
    waiting_for_car_date = State()
    waiting_for_car_time = State()
    waiting_for_car_duration = State()
    waiting_for_car_location = State()
    waiting_for_photo = State()
    waiting_for_urgency = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_comment = State()
    waiting_for_planned_date = State()
    waiting_for_confirmation = State()