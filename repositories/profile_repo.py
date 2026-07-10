"""Репозиторий для операций ленты анкет.

PERF: next_candidate_and_mark / next_candidate_full минимизируют round-trip к БД.

FIX (#9 рефакторинг): общий SQL-фильтр ленты (FROM + WHERE + ORDER + LIMIT) и
 порядок параметров вынесены в _FEED_TAIL и _feed_params(). Раньше идентичный
 блок и кортеж из 9 параметров были скопированы в трёх функциях — правка
 фильтра в одном месте молча ломала ленту. Теперь единый источник правды,
 функции отличаются только SELECT-проекцией.
FIX v7: параметризованные запросы, без f-string и inline __import__.

ПРИМЕЧАНИЕ по порядку параметров (сохранён из рабочей версии):
  плейсхолдеры WHERE идут так:
    sp.from_id, l.from_id, u.tg_id,
    (? = 'any' OR u.gender = ?)              -> seeking, seeking
    (? = '' OR u.seeking = ? OR 'any')       -> gender, gender
    age BETWEEN ? AND ?                        -> min_age, max_age
  Логика: "seeking='any' ИЛИ пол кандидата = seeking зрителя" и
          "пол зрителя='' ИЛИ кандидат ищет пол зрителя ИЛИ ищет любой".
"""
import time as _time
from typing import Optional

from database.connection import db

# Хвост запроса ленты — одинаков для всех вариантов, меняется только SELECT.
_FEED_TAIL = """
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
"""


def _feed_params(viewer_id: int, viewer: dict) -> tuple:
    """Кортеж параметров под _FEED_TAIL (порядок строго соответствует плейсхолдерам)."""
    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99
    return (
        viewer_id,   # sp.from_id
        viewer_id,   # l.from_id
        viewer_id,   # u.tg_id != ?
        seeking,     # ? = 'any'
        seeking,     # u.gender = ?
        gender,      # ? = ''
        gender,      # u.seeking = ?
        min_age,     # age >= ?
        max_age,     # age <= ?
    )


async def _mark_shown(conn, from_id: int, to_id: int) -> None:
    """Отмечает профиль показанным (в переданном соединении/транзакции)."""
    await conn.execute(
        """
        INSERT OR IGNORE INTO shown_profiles (from_id, to_id, shown_at)
        VALUES (?, ?, ?)
        """,
        (from_id, to_id, int(_time.time())),
    )


async def next_candidate_and_mark(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Находит следующего кандидата И отмечает его показанным."""
    if viewer is None:
        return None

    async with db() as conn:
        cursor = await conn.execute(
            "SELECT u.* " + _FEED_TAIL,
            _feed_params(viewer_id, viewer),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        await _mark_shown(conn, viewer_id, row["tg_id"])
        return dict(row)


async def next_candidate_full(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Находит кандидата с предзагруженными photo_count и badge_ids."""
    if viewer is None:
        return None

    select = """
        SELECT u.*,
               (SELECT COUNT(*) FROM photos p WHERE p.tg_id = u.tg_id) AS photo_count,
               (SELECT GROUP_CONCAT(badge_id) FROM user_badges ub WHERE ub.tg_id = u.tg_id) AS badge_ids_str
    """
    async with db() as conn:
        cursor = await conn.execute(select + _FEED_TAIL, _feed_params(viewer_id, viewer))
        row = await cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        result["photo_count"] = row["photo_count"] or 0
        badge_str = row["badge_ids_str"]
        result["badge_ids"] = badge_str.split(",") if badge_str else []

        await _mark_shown(conn, viewer_id, result["tg_id"])
        return result


async def next_candidate(
    viewer_id: int, viewer: dict | None = None
) -> Optional[dict]:
    """Возвращает следующего кандидата для ленты (без mark_shown)."""
    if viewer is None:
        return None

    async with db() as conn:
        cursor = await conn.execute(
            "SELECT u.* " + _FEED_TAIL,
            _feed_params(viewer_id, viewer),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def mark_shown(from_id: int, to_id: int) -> None:
    """Отмечает профиль как показанный."""
    async with db() as conn:
        await _mark_shown(conn, from_id, to_id)


async def cleanup_shown_profiles(max_age_days: int = 30) -> int:
    """Удаляет записи shown_profiles старше max_age_days дней."""
    cutoff = int(_time.time()) - max_age_days * 86400
    async with db() as conn:
        cursor = await conn.execute(
            "DELETE FROM shown_profiles WHERE shown_at < ? AND shown_at > 0",
            (cutoff,),
        )
        return cursor.rowcount
