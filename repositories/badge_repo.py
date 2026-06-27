"""Репозиторий для операций со значками."""
from database.connection import get_db, get_single_db


async def get_user_badge_ids(tg_id: int) -> set[str]:
    """Возвращает ID значков пользователя."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT badge_id FROM user_badges WHERE tg_id = ?",
        (tg_id,)
    )
    rows = await cur.fetchall()
    return {r["badge_id"] for r in rows}


async def award_badge(tg_id: int, badge_id: str, awarded_at: int) -> None:
    """Записывает значок в БД."""
    conn = await get_single_db()
    await conn.execute(
        "INSERT OR IGNORE INTO user_badges (tg_id, badge_id, awarded_at) VALUES (?, ?, ?)",
        (tg_id, badge_id, awarded_at)
    )
    await conn.commit()
    await conn.close()


async def get_user_stats(tg_id: int) -> dict:
    """Возвращает все статистики пользователя одним запросом.

    Оптимизация: вместо 5 отдельных COUNT-запросов — один агрегированный.
    """
    conn = await get_db()
    cur = await conn.execute("""
        SELECT 
            (SELECT COUNT(*) FROM matches WHERE a_id = ? OR b_id = ?) as matches,
            (SELECT COUNT(*) FROM likes WHERE from_id = ? AND is_like = 1) as likes_sent,
            (SELECT COUNT(*) FROM reports WHERE from_id = ?) as reports_sent,
            (SELECT COUNT(*) FROM likes WHERE from_id = ? AND is_like = 1 AND message IS NOT NULL) as msglikes
    """, (tg_id, tg_id, tg_id, tg_id, tg_id))
    row = await cur.fetchone()
    return {
        "matches": row["matches"] if row else 0,
        "likes_sent": row["likes_sent"] if row else 0,
        "reports_sent": row["reports_sent"] if row else 0,
        "msglikes": row["msglikes"] if row else 0,
    }
