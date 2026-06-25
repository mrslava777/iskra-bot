"""Сборка всех роутеров."""
from aiogram import Router

from . import admin, start, browse, profile, likes, anon, support, misc, badges


def setup_routers() -> Router:
    root = Router()
    root.include_router(admin.router)  # первый: перехватывает /admin, /ban, /unban, /broadcast
    root.include_router(start.router)
    root.include_router(profile.router)
    root.include_router(likes.router)
    root.include_router(browse.router)
    root.include_router(anon.router)  # перед misc: ловит чат-сессии и /stop
    root.include_router(badges.router)  # NEW: система Артефактов
    root.include_router(support.router)
    root.include_router(misc.router)
    return root
