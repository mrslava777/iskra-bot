"""Anonymous chat handlers — свидание вслепую."""
from aiogram import Router

from handlers.anon.chat import router as chat_router
from handlers.anon.queue import router as queue_router


def setup_anon_router() -> Router:
    """Собирает все anon-роутеры."""
    root = Router()
    root.include_router(queue_router)
    root.include_router(chat_router)
    return root
