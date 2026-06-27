"""Profile handlers — просмотр и редактирование анкеты."""
from aiogram import Router

from handlers.profile.view import router as view_router
from handlers.profile.edit import router as edit_router
from handlers.profile.photos import router as photos_router
from handlers.profile.settings import router as settings_router
from handlers.profile.verification import router as verify_router
from handlers.profile.daily import router as daily_router


def setup_profile_router() -> Router:
    """Собирает все profile-роутеры.

    ВАЖНО: роутеры с ТОЧНЫМИ (конкретными) фильтрами должны идти ПЕРЕД
    роутерами с ШИРОКИМИ фильтрами. Иначе широкий фильтр перехватит
    callback'ы, предназначенные для конкретного обработчика.

    Порядок:
    1. view_router    — нет callback-фильтров
    2. photos_router  — точный фильтр: ed:photos
    3. verify_router  — точный фильтр: ed:verify
    4. daily_router   — точные фильтры: ed:daily, ed:del_daily
    5. settings_router — префикс set: (не конфликтует с ed:)
    6. edit_router    — широкий фильтр: ed:{name,age,city,bio,interests}
    """
    root = Router()
    root.include_router(view_router)
    root.include_router(photos_router)
    root.include_router(verify_router)
    root.include_router(daily_router)
    root.include_router(settings_router)
    root.include_router(edit_router)
    return root
