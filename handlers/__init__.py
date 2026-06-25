"""Инициализация хендлеров — собирает все роутеры."""
from aiogram import Router

from handlers.admin import router as admin_router
from handlers.anon import router as anon_router
from handlers.badges import router as badges_router
from handlers.browse import router as browse_router
from handlers.likes import router as likes_router
from handlers.misc import router as misc_router
from handlers.profile import router as profile_router
from handlers.start import router as start_router
from handlers.support import router as support_router


def setup_routers() -> Router:
    """Собирает все роутеры в один корневой."""
    root = Router()
    root.include_router(start_router)
    root.include_router(browse_router)
    root.include_router(likes_router)
    root.include_router(profile_router)
    root.include_router(anon_router)
    root.include_router(badges_router)
    root.include_router(support_router)
    root.include_router(admin_router)
    root.include_router(misc_router)  # misc — последний, ловит fallback
    return root
