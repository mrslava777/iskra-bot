"""Репозиторий списков пользователей для админ-панели."""
from database.connection import db


async def get_verified_users(limit: int = 20) -> list[dict]:
    """Возвращает верифицированных пользователей."""
    async with db() as conn:
        rows = await conn.fetch(
            """
            SELECT tg_id, name, username, age
            FROM users
            WHERE verified = 1
            ORDER BY last_active DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
