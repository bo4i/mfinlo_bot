from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_phone_number = State()
    waiting_for_organization_choice = State()
    waiting_for_manual_organization_input = State()
    waiting_for_office_number = State()