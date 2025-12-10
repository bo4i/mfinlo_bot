from aiogram.fsm.state import State, StatesGroup


class AdminCompletionState(StatesGroup):
    waiting_for_feedback = State()