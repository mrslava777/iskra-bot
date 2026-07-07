"""Репозиторий мэтчей (взаимных лайков)."""
from database.connection import db


async def get_matches(tg_id: int) -> list[dict]:
    """Возвращает анкеты собеседников из мэтчей пользователя."""
    async with db() as conn:
        cursor = await conn.execute(
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
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_matches_batch(tg_ids: list[int]) -> dict[int, list[dict]]:
    """Batch-загрузка мэтчей для нескольких пользователей.

    Оптимизация: один запрос вместо N запросов.
    """
    if not tg_ids:
        return {}

    async with db() as conn:
        placeholders = ','.join('?' for _ in tg_ids)
        cursor = await conn.execute(
            f"""
            SELECT u.*, m.created_at AS matched_at,
                   CASE WHEN m.a_id IN ({placeholders}) THEN m.a_id ELSE m.b_id END AS viewer_id
            FROM matches m
            JOIN users u ON u.tg_id = CASE
                WHEN m.a_id IN ({placeholders}) THEN m.b_id
                ELSE m.a_id
            END
            WHERE (m.a_id IN ({placeholders}) OR m.b_id IN ({placeholders}))
              AND u.is_banned = 0
            ORDER BY m.created_at DESC
            """,
            tuple(tg_ids + tg_ids + tg_ids + tg_ids),
        )
        rows = await cursor.fetchall()

        result: dict[int, list[dict]] = {uid: [] for uid in tg_ids}
        for r in rows:
            viewer = r["viewer_id"]
            if viewer in result:
                result[viewer].append(dict(r))
        return result
