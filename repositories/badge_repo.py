"""Репозиторий для операций со значками."""
from database.connection import db, get_single_db


async def get_user_badge_ids(tg_id: int) -> set[str]:
    """Возвращает ID значков пользователя."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT badge_id FROM user_badges WHERE tg_id = $1",
            tg_id,
        )
        return {r["badge_id"] for r in rows}


async def award_badge(tg_id: int, badge_id: str, awarded_at: int) -> None:
    """Записывает значок в БД."""
    conn = await get_single_db()
    try:
        await conn.execute(
            """
            INSERT INTO user_badges (tg_id, badge_id, awarded_at) VALUES ($1, $2, $3)
            ON CONFLICT (tg_id, badge_id) DO NOTHING
            """,
            tg_id, badge_id, awarded_at,
        )
    finally:
        await conn.close()


async def get_user_stats(tg_id: int) -> dict:
    """Возвращает все статистики пользователя одним запросом."""
    async with db() as conn:
        row = await conn.fetchrow("""
            SELECT 
                (SELECT COUNT(*) FROM matches WHERE a_id = $1 OR b_id = $1) as matches,
                (SELECT COUNT(*) FROM likes WHERE from_id = $2 AND is_like = 1) as likes_sent,
                (SELECT COUNT(*) FROM reports WHERE from_id = $3) as reports_sent,
                (SELECT COUNT(*) FROM likes WHERE from_id = $4 AND is_like = 1 AND message IS NOT NULL) as msglikes
        """, tg_id, tg_id, tg_id, tg_id)
        return {
            "matches": row["matches"] if row else 0,
            "likes_sent": row["likes_sent"] if row else 0,
            "reports_sent": row["reports_sent"] if row else 0,
            "msglikes": row["msglikes"] if row else 0,
        }
