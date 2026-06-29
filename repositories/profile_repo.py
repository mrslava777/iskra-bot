"""Репозиторий для операций ленты анкет.

PERF: next_candidate_and_mark — CTE объединяет поиск кандидата и mark_shown
     в один SQL-запрос (было 2 запроса → 2 round-trip к БД, стало 1).
PERF v5: next_candidate_full — batch-загружает photo_count + badge_ids
     в том же CTE, убирая 2 дополнительных запроса.
"""
from typing import Optional

from database.connection import db


async def next_candidate_and_mark(viewer_id: int, viewer: dict | None = None) -> Optional[dict]:
    """Находит следующего кандидата И отмечает его как показанного — одним запросом.

    PERF: CTE объединяет SELECT + INSERT в один round-trip к БД.
    Было: next_candidate() + mark_shown() = 2 запроса.
    Стало: 1 запрос с CTE.
    """
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        row = await conn.fetchrow(
            """
            WITH cand AS (
                SELECT u.* FROM users u
                LEFT JOIN shown_profiles sp ON sp.from_id = $1 AND sp.to_id = u.tg_id
                LEFT JOIN likes l ON l.from_id = $1 AND l.to_id = u.tg_id
                WHERE u.tg_id != $1
                  AND u.active = 1
                  AND u.is_banned = 0
                  AND u.photo_id IS NOT NULL
                  AND u.name IS NOT NULL
                  AND sp.to_id IS NULL
                  AND l.to_id IS NULL
                  AND ($2 = 'any' OR u.gender = $2)
                  AND ($3 = '' OR u.seeking = $3 OR u.seeking = 'any')
                  AND u.age BETWEEN $4 AND $5
                ORDER BY u.last_active DESC
                LIMIT 1
            ), mark AS (
                INSERT INTO shown_profiles (from_id, to_id, shown_at)
                SELECT $1, tg_id, EXTRACT(EPOCH FROM NOW())::INTEGER FROM cand
                ON CONFLICT (from_id, to_id) DO NOTHING
            )
            SELECT * FROM cand
            """,
            viewer_id, seeking, gender, min_age, max_age,
        )
        return dict(row) if row else None


async def next_candidate_full(viewer_id: int, viewer: dict | None = None) -> Optional[dict]:
    """Находит кандидата с предзагруженными photo_count и badge_ids.

    PERF v5: один SQL-запрос вместо 3 (candidate + photo_count + badges).
    Экономия: ~2 round-trip к БД, ~300-600 мс на медленных соединениях.
    """
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        row = await conn.fetchrow(
            """
            WITH cand AS (
                SELECT u.*,
                       (SELECT COUNT(*) FROM photos p WHERE p.tg_id = u.tg_id) as photo_count,
                       (SELECT array_agg(badge_id) FROM user_badges ub WHERE ub.tg_id = u.tg_id) as badge_ids
                FROM users u
                LEFT JOIN shown_profiles sp ON sp.from_id = $1 AND sp.to_id = u.tg_id
                LEFT JOIN likes l ON l.from_id = $1 AND l.to_id = u.tg_id
                WHERE u.tg_id != $1
                  AND u.active = 1
                  AND u.is_banned = 0
                  AND u.photo_id IS NOT NULL
                  AND u.name IS NOT NULL
                  AND sp.to_id IS NULL
                  AND l.to_id IS NULL
                  AND ($2 = 'any' OR u.gender = $2)
                  AND ($3 = '' OR u.seeking = $3 OR u.seeking = 'any')
                  AND u.age BETWEEN $4 AND $5
                ORDER BY u.last_active DESC
                LIMIT 1
            ), mark AS (
                INSERT INTO shown_profiles (from_id, to_id, shown_at)
                SELECT $1, tg_id, EXTRACT(EPOCH FROM NOW())::INTEGER FROM cand
                ON CONFLICT (from_id, to_id) DO NOTHING
            )
            SELECT * FROM cand
            """,
            viewer_id, seeking, gender, min_age, max_age,
        )
        if not row:
            return None
        result = dict(row)
        result["photo_count"] = row["photo_count"] or 0
        result["badge_ids"] = row["badge_ids"] or []
        return result


async def next_candidate(viewer_id: int, viewer: dict | None = None) -> Optional[dict]:
    """Возвращает следующего кандидата для ленты (без mark_shown).

    Оставлен для обратной совместимости.
    Предпочитай next_candidate_and_mark() — он экономит один DB round-trip.
    """
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.* FROM users u
            LEFT JOIN shown_profiles sp ON sp.from_id = $1 AND sp.to_id = u.tg_id
            LEFT JOIN likes l ON l.from_id = $1 AND l.to_id = u.tg_id
            WHERE u.tg_id != $1
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND u.name IS NOT NULL
              AND sp.to_id IS NULL
              AND l.to_id IS NULL
              AND ($2 = 'any' OR u.gender = $2)
              AND ($3 = '' OR u.seeking = $3 OR u.seeking = 'any')
              AND u.age BETWEEN $4 AND $5
            ORDER BY u.last_active DESC
            LIMIT 1
            """,
            viewer_id, seeking, gender, min_age, max_age,
        )
        return dict(row) if row else None


async def mark_shown(from_id: int, to_id: int) -> None:
    """Отмечает профиль как показанный."""
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO shown_profiles (from_id, to_id, shown_at)
            VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::INTEGER)
            ON CONFLICT (from_id, to_id) DO NOTHING
            """,
            from_id, to_id,
        )


async def cleanup_shown_profiles(max_age_days: int = 30) -> int:
    """Удаляет записи shown_profiles старше max_age_days дней."""
    import time
    cutoff = int(time.time()) - max_age_days * 86400
    async with db() as conn:
        result = await conn.execute(
            "DELETE FROM shown_profiles WHERE shown_at < $1 AND shown_at > 0",
            cutoff,
        )
        count = int(result.split()[-1]) if result else 0
        return count
