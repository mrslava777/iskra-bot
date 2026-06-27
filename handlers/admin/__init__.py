"""Admin handlers — админ-панель бота."""
from aiogram import Router

from handlers.admin.stats import router as stats_router
from handlers.admin.users import router as users_router
from handlers.admin.moderation import router as moderation_router
from handlers.admin.broadcast import router as broadcast_router
from handlers.admin.badges import router as badges_router


def setup_admin_router() -> Router:
    """Собирает все admin-роутеры."""
    root = Router()
    root.include_router(stats_router)
    root.include_router(users_router)
    root.include_router(moderation_router)
    root.include_router(broadcast_router)
    root.include_router(badges_router)
    return root
