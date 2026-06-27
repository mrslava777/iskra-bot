"""Profile handlers — просмотр и редактирование анкеты."""
from aiogram import Router

from handlers.profile.view import router as view_router
from handlers.profile.edit import router as edit_router
from handlers.profile.photos import router as photos_router
from handlers.profile.settings import router as settings_router
from handlers.profile.verification import router as verify_router
from handlers.profile.daily import router as daily_router


def setup_profile_router() -> Router:
    """Собирает все profile-роутеры."""
    root = Router()
    root.include_router(view_router)
    root.include_router(edit_router)
    root.include_router(photos_router)
    root.include_router(settings_router)
    root.include_router(verify_router)
    root.include_router(daily_router)
    return root
