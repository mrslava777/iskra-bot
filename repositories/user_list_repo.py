"""Репозиторий списков пользователей для админ-панели."""
from database.connection import get_db


async def get_verified_users(limit: int = 20) -> list[dict]:
    """Возвращает верифицированных пользователей."""
    conn = await get_db()
    cur = await conn.execute(
        """
        SELECT tg_id, name, username, age
        FROM users
        WHERE verified = 1
        ORDER BY last_active DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]
