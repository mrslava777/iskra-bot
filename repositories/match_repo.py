"""Репозиторий мэтчей (взаимных лайков)."""
from database.connection import db


async def get_matches(tg_id: int) -> list[dict]:
    """Возвращает анкеты собеседников из мэтчей пользователя."""
    async with db() as conn:
        rows = await conn.fetch(
            """
            SELECT u.*, m.created_at AS matched_at
            FROM matches m
            JOIN users u ON u.tg_id = CASE
                WHEN m.a_id = $1 THEN m.b_id
                ELSE m.a_id
            END
            WHERE (m.a_id = $2 OR m.b_id = $3)
              AND u.is_banned = 0
            ORDER BY m.created_at DESC
            """,
            tg_id, tg_id, tg_id,
        )
        return [dict(r) for r in rows]


async def get_matches_batch(tg_ids: list[int]) -> dict[int, list[dict]]:
    """Batch-загрузка мэтчей для нескольких пользователей.

    Оптимизация: один запрос вместо N запросов.
    """
    if not tg_ids:
        return {}

    async with db() as conn:
        placeholders = ','.join(f'${i+1}' for i in range(len(tg_ids)))
        rows = await conn.fetch(
            f"""
            SELECT u.*, m.created_at AS matched_at,
                   CASE WHEN m.a_id = ANY(ARRAY[{placeholders}]) THEN m.a_id ELSE m.b_id END AS viewer_id
            FROM matches m
            JOIN users u ON u.tg_id = CASE
                WHEN m.a_id = ANY(ARRAY[{placeholders}]) THEN m.b_id
                ELSE m.a_id
            END
            WHERE (m.a_id = ANY(ARRAY[{placeholders}]) OR m.b_id = ANY(ARRAY[{placeholders}]))
              AND u.is_banned = 0
            ORDER BY m.created_at DESC
            """,
            *tg_ids, *tg_ids, *tg_ids, *tg_ids,
        )

        result: dict[int, list[dict]] = {uid: [] for uid in tg_ids}
        for r in rows:
            viewer = r["viewer_id"]
            if viewer in result:
                result[viewer].append(dict(r))
        return result
