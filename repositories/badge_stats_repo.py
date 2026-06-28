"""Репозиторий статистики значков (для админ-панели)."""
from database.connection import db


async def get_badge_count(badge_id: str) -> int:
    """Возвращает количество обладателей значка."""
    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) c FROM user_badges WHERE badge_id = $1",
            badge_id,
        )
        return row["c"] if row else 0


async def get_all_badge_counts() -> dict[str, int]:
    """Возвращает количество обладателей всех значков одним запросом."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT badge_id, COUNT(*) as c FROM user_badges GROUP BY badge_id"
        )
        return {r["badge_id"]: r["c"] for r in rows}


async def get_top_collectors(limit: int = 10) -> list:
    """Возвращает топ коллекционеров."""
    async with db() as conn:
        rows = await conn.fetch(
            """SELECT tg_id, COUNT(*) as cnt FROM user_badges GROUP BY tg_id ORDER BY cnt DESC LIMIT $1""",
            limit,
        )
        return [dict(r) for r in rows]
