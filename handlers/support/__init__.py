"""Support handlers — обращения в поддержку."""
from aiogram import Router

from handlers.support.ticket import router as ticket_router
from handlers.support.reply import router as reply_router


def setup_support_router() -> Router:
    """Собирает все support-роутеры."""
    root = Router()
    root.include_router(ticket_router)
    root.include_router(reply_router)
    return root
