"""Репозиторий мэтчей (взаимных лайков)."""
from database.connection import get_db


async def get_matches(tg_id: int) -> list[dict]:
    """Возвращает анкеты собеседников из мэтчей пользователя."""
    conn = await get_db()
    cur = await conn.execute(
        """
        SELECT u.*, m.created_at AS matched_at
        FROM matches m
        JOIN users u ON u.tg_id = CASE
            WHEN m.a_id = ? THEN m.b_id
            ELSE m.a_id
        END
        WHERE (m.a_id = ? OR m.b_id = ?)
          AND u.is_banned = 0
        ORDER BY m.created_at DESC
        """,
        (tg_id, tg_id, tg_id),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]
