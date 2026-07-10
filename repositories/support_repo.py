"""Репозиторий тикетов поддержки.

FIX (#8): убран inline __import__('time'); импорт вынесен наверх модуля.
"""
import time
from typing import Optional

from database.connection import db


async def create_ticket(
    tg_id: int,
    category: str,
    text: str,
    photo_id: Optional[str] = None,
) -> int:
    """Создаёт тикет и возвращает его id."""
    now = int(time.time())
    async with db() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO tickets (tg_id, category, text, photo_id, status, created_at)
            VALUES (?, ?, ?, ?, 'open', ?)
            """,
            (tg_id, category, text, photo_id, now),
        )
        return cursor.lastrowid


async def reply_ticket(ticket_id: int, reply_text: str) -> None:
    """Сохраняет ответ администратора и помечает тикет отвеченным."""
    async with db() as conn:
        await conn.execute(
            "UPDATE tickets SET reply = ?, status = 'replied' WHERE id = ?",
            (reply_text, ticket_id),
        )
