from aiogram.fsm.state import State, StatesGroup


class ClarificationState(StatesGroup):
    admin_active_dialogue = State()
    user_active_dialogue = State()