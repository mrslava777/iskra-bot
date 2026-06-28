"""Репозиторий тикетов поддержки."""
from typing import Optional

from database.connection import db, get_single_db


async def create_ticket(
    tg_id: int,
    category: str,
    text: str,
    photo_id: Optional[str] = None,
) -> int:
    """Создаёт тикет и возвращает его id."""
    async with db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tickets (tg_id, category, text, photo_id, status, created_at)
            VALUES ($1, $2, $3, $4, 'open', EXTRACT(EPOCH FROM NOW())::INTEGER)
            RETURNING id
            """,
            tg_id, category, text, photo_id,
        )
        return row["id"] if row else 0


async def reply_ticket(ticket_id: int, reply_text: str) -> None:
    """Сохраняет ответ администратора и помечает тикет отвеченным."""
    async with db() as conn:
        await conn.execute(
            "UPDATE tickets SET reply = $1, status = 'replied' WHERE id = $2",
            reply_text, ticket_id,
        )
