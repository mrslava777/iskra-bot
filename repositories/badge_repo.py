"""Репозиторий для операций со значками."""
from database.connection import db


async def get_user_badge_ids(tg_id: int) -> set[str]:
    """Возвращает ID значков пользователя."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT badge_id FROM user_badges WHERE tg_id = $1",
            tg_id,
        )
        return {r["badge_id"] for r in rows}


async def get_user_badge_ids_batch(tg_ids: list[int]) -> dict[int, set[str]]:
    """Возвращает ID значков для нескольких пользователей одним запросом.

    Оптимизация: вместо N запросов get_user_badge_ids() — один batch-запрос.
    """
    if not tg_ids:
        return {}
    async with db() as conn:
        placeholders = ",".join(f"${i+1}" for i in range(len(tg_ids)))
        rows = await conn.fetch(
            f"SELECT tg_id, badge_id FROM user_badges WHERE tg_id IN ({placeholders})",
            *tg_ids,
        )
        result: dict[int, set[str]] = {}
        for r in rows:
            uid = r["tg_id"]
            if uid not in result:
                result[uid] = set()
            result[uid].add(r["badge_id"])
        return result


async def award_badge(tg_id: int, badge_id: str, awarded_at: int) -> None:
    """Записывает значок в БД."""
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO user_badges (tg_id, badge_id, awarded_at) VALUES ($1, $2, $3)
            ON CONFLICT (tg_id, badge_id) DO NOTHING
            """,
            tg_id, badge_id, awarded_at,
        )


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
