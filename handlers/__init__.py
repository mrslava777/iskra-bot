"""Инициализация хендлеров — собирает все роутеры."""
from aiogram import Router

from handlers.admin import setup_admin_router
from handlers.anon import setup_anon_router
from handlers.badges import router as badges_router
from handlers.matching import setup_matching_router
from handlers.misc import router as misc_router
from handlers.profile import setup_profile_router
from handlers.start import router as start_router
from handlers.support import setup_support_router


def setup_routers() -> Router:
    """Собирает все роутеры в один корневой."""
    root = Router()
    root.include_router(start_router)
    root.include_router(setup_matching_router())
    root.include_router(setup_profile_router())
    root.include_router(setup_anon_router())
    root.include_router(badges_router)
    root.include_router(setup_support_router())
    root.include_router(setup_admin_router())
    root.include_router(misc_router)
    return root
