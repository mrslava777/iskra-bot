"""Сборка всех роутеров."""
from aiogram import Router

from . import start, browse, profile, likes, misc


def setup_routers() -> Router:
    root = Router()
    root.include_router(start.router)
    root.include_router(profile.router)
    root.include_router(likes.router)
    root.include_router(browse.router)
    root.include_router(misc.router)
    return root
