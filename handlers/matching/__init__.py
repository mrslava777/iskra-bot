"""Matching handlers — лента, лайки, мэтчи."""
from aiogram import Router

from handlers.matching.browse import router as browse_router
from handlers.matching.likes import router as likes_router
from handlers.matching.matches import router as matches_router


def setup_matching_router() -> Router:
    """Собирает все matching-роутеры."""
    root = Router()
    root.include_router(browse_router)
    root.include_router(likes_router)
    root.include_router(matches_router)
    return root
