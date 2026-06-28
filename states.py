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
    extra_photos = State()


class Edit(StatesGroup):
    field = State()
    value = State()
    interests = State()
    filters_age = State()
    photos = State()


class Verify(StatesGroup):
    video_note = State()


class Support(StatesGroup):
    message = State()
    admin_reply = State()
