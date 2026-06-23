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
    voice = State()          # <-- NEW: голосовое приветствие
    extra_photos = State()


class Edit(StatesGroup):
    field = State()
    value = State()
    interests = State()
    daily = State()
    filters_age = State()
    photos = State()
    voice = State()          # <-- NEW


class Verify(StatesGroup):
    photo = State()


class Support(StatesGroup):
    message = State()
    admin_reply = State()
