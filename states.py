"""FSM-состояния регистрации и редактирования анкеты."""
from aiogram.fsm.state import State, StatesGroup


class Reg(StatesGroup):
    name = State()
    age = State()
    gender = State()
    seeking = State()
    city = State()
    interests = State()
    bio = State()
    photo = State()


class Edit(StatesGroup):
    field = State()
    value = State()
    interests = State()
    daily = State()
    filters_age = State()
