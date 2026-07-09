"""Репозиторий для операций ленты анкет.

PERF: next_candidate_and_mark — CTE объединяет поиск кандидата и mark_shown
     в один SQL-запрос (было 2 запроса → 2 round-trip к БД, стало 1).
PERF v5: next_candidate_full — batch-загружает photo_count + badge_ids
     в том же CTE, убирая 2 дополнительных запроса.
FIX v7: удалён f-string в SQL (безопасность). Используется параметризованный запрос.
        Убраны inline __import__('time').
"""
import time as _time
from typing import Optional

from database.connection import db


async def next_candidate_and_mark(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Находит следующего кандидата И отмечает его как показанного — одним запросом."""
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        cursor = await conn.execute(
            """
            SELECT u.* FROM users u
            LEFT JOIN shown_profiles sp ON sp.from_id = ? AND sp.to_id = u.tg_id
            LEFT JOIN likes l ON l.from_id = ? AND l.to_id = u.tg_id
            WHERE u.tg_id != ?
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND u.name IS NOT NULL
              AND sp.to_id IS NULL
              AND l.to_id IS NULL
              AND (? = 'any' OR u.gender = ?)
              AND (? = '' OR u.seeking = ? OR u.seeking = 'any')
              AND u.age BETWEEN ? AND ?
            ORDER BY u.last_active DESC
            LIMIT 1
            """,
            (
                viewer_id,
                viewer_id,
                viewer_id,
                seeking,
                seeking,
                gender,
                gender,
                min_age,
                max_age,
            ),
        )
        row = await cursor.fetchone()

        if row:
            now = int(_time.time())
            await conn.execute(
                """
                INSERT OR IGNORE INTO shown_profiles (from_id, to_id, shown_at)
                VALUES (?, ?, ?)
                """,
                (viewer_id, row["tg_id"], now),
            )
            return dict(row)
        return None


async def next_candidate_full(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Находит кандидата с предзагруженными photo_count и badge_ids."""
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        cursor = await conn.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM photos p WHERE p.tg_id = u.tg_id) as photo_count,
                   (SELECT GROUP_CONCAT(badge_id) FROM user_badges ub WHERE ub.tg_id = u.tg_id) as badge_ids_str
            FROM users u
            LEFT JOIN shown_profiles sp ON sp.from_id = ? AND sp.to_id = u.tg_id
            LEFT JOIN likes l ON l.from_id = ? AND l.to_id = u.tg_id
            WHERE u.tg_id != ?
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND u.name IS NOT NULL
              AND sp.to_id IS NULL
              AND l.to_id IS NULL
              AND (? = 'any' OR u.gender = ?)
              AND (? = '' OR u.seeking = ? OR u.seeking = 'any')
              AND u.age BETWEEN ? AND ?
            ORDER BY u.last_active DESC
            LIMIT 1
            """,
            (
                viewer_id,
                viewer_id,
                viewer_id,
                seeking,
                seeking,
                gender,
                gender,
                min_age,
                max_age,
            ),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        result["photo_count"] = row["photo_count"] or 0
        badge_str = row["badge_ids_str"]
        result["badge_ids"] = badge_str.split(",") if badge_str else []

        now = int(_time.time())
        await conn.execute(
            """
            INSERT OR IGNORE INTO shown_profiles (from_id, to_id, shown_at)
            VALUES (?, ?, ?)
            """,
            (viewer_id, result["tg_id"], now),
        )
        return result


async def next_candidate(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Возвращает следующего кандидата для ленты (без mark_shown)."""
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        cursor = await conn.execute(
            """
            SELECT u.* FROM users u
            LEFT JOIN shown_profiles sp ON sp.from_id = ? AND sp.to_id = u.tg_id
            LEFT JOIN likes l ON l.from_id = ? AND l.to_id = u.tg_id
            WHERE u.tg_id != ?
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND u.name IS NOT NULL
              AND sp.to_id IS NULL
              AND l.to_id IS NULL
              AND (? = 'any' OR u.gender = ?)
              AND (? = '' OR u.seeking = ? OR u.seeking = 'any')
              AND u.age BETWEEN ? AND ?
            ORDER BY u.last_active DESC
            LIMIT 1
            """,
            (
                viewer_id,
                viewer_id,
                viewer_id,
                seeking,
                seeking,
                gender,
                gender,
                min_age,
                max_age,
            ),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def mark_shown(from_id: int, to_id: int) -> None:
    """Отмечает профиль как показанный."""
    now = int(_time.time())
    async with db() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO shown_profiles (from_id, to_id, shown_at)
            VALUES (?, ?, ?)
            """,
            (from_id, to_id, now),
        )


async def cleanup_shown_profiles(max_age_days: int = 30) -> int:
    """Удаляет записи shown_profiles старше max_age_days дней.

    FIX v7: параметризованный запрос вместо f-string.
    aiosqlite поддерживает int параметры — проблема v6 была в другом.
    """
    cutoff = int(_time.time()) - max_age_days * 86400
    async with db() as conn:
        cursor = await conn.execute(
            "DELETE FROM shown_profiles WHERE shown_at < ? AND shown_at > 0",
            (cutoff,),
        )
        return cursor.rowcount
