"""Репозиторий тикетов поддержки."""
from typing import Optional

from database.connection import get_db, get_single_db


async def create_ticket(
    tg_id: int,
    category: str,
    text: str,
    photo_id: Optional[str] = None,
) -> int:
    """Создаёт тикет и возвращает его id."""
    conn = await get_single_db()
    try:
        cur = await conn.execute(
            """
            INSERT INTO tickets (tg_id, category, text, photo_id, status, created_at)
            VALUES (?, ?, ?, ?, 'open', strftime('%s','now'))
            RETURNING id
            """,
            (tg_id, category, text, photo_id),
        )
        row = await cur.fetchone()
        await conn.commit()
        return row["id"] if row else 0
    finally:
        await conn.close()


async def reply_ticket(ticket_id: int, reply_text: str) -> None:
    """Сохраняет ответ администратора и помечает тикет отвеченным."""
    conn = await get_single_db()
    try:
        await conn.execute(
            "UPDATE tickets SET reply = ?, status = 'replied' WHERE id = ?",
            (reply_text, ticket_id),
        )
        await conn.commit()
    finally:
        await conn.close()
