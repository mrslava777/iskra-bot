"""Репозиторий для операций со значками.

PERF: get_user_badge_ids() кэшируется на 30 секунд.
Значки выдаются редко, но проверяются часто (format_profile_async, check_and_award).
"""
import time
from collections import OrderedDict

from database.connection import db

# TTL-кэш для badge_ids
_badge_cache: OrderedDict[int, tuple[set[str], float]] = OrderedDict()
_BADGE_CACHE_TTL = 30
_BADGE_CACHE_MAX = 500


def _invalidate_badges(tg_id: int) -> None:
    """Сбрасывает кэш значков после выдачи нового."""
    _badge_cache.pop(tg_id, None)


async def get_user_badge_ids(tg_id: int) -> set[str]:
    """Возвращает ID значков пользователя (с TTL-кэшем)."""
    now = time.monotonic()
    cached = _badge_cache.get(tg_id)
    if cached is not None:
        ids, cached_at = cached
        if now - cached_at < _BADGE_CACHE_TTL:
            _badge_cache.move_to_end(tg_id)
            return ids

    async with db() as conn:
        cursor = await conn.execute(
            "SELECT badge_id FROM user_badges WHERE tg_id = ?",
            (tg_id,),
        )
        rows = await cursor.fetchall()
        result = {r["badge_id"] for r in rows}

    _badge_cache[tg_id] = (result, now)
    if len(_badge_cache) > _BADGE_CACHE_MAX:
        _badge_cache.popitem(last=False)
    return result


async def get_user_badge_ids_batch(tg_ids: list[int]) -> dict[int, set[str]]:
    """Возвращает ID значков для нескольких пользователей одним запросом."""
    if not tg_ids:
        return {}

    # Проверяем кэш — может, все уже есть
    now = time.monotonic()
    result: dict[int, set[str]] = {}
    missing: list[int] = []
    for uid in tg_ids:
        cached = _badge_cache.get(uid)
        if cached is not None:
            ids, cached_at = cached
            if now - cached_at < _BADGE_CACHE_TTL:
                result[uid] = ids
                continue
        missing.append(uid)

    if not missing:
        return result

    async with db() as conn:
        placeholders = ",".join("?" for _ in missing)
        cursor = await conn.execute(
            f"SELECT tg_id, badge_id FROM user_badges WHERE tg_id IN ({placeholders})",
            tuple(missing),
        )
        rows = await cursor.fetchall()
        fetched: dict[int, set[str]] = {}
        for r in rows:
            uid = r["tg_id"]
            if uid not in fetched:
                fetched[uid] = set()
            fetched[uid].add(r["badge_id"])

        # Заполняем кэш и результат
        for uid in missing:
            ids = fetched.get(uid, set())
            _badge_cache[uid] = (ids, now)
            result[uid] = ids

        if len(_badge_cache) > _BADGE_CACHE_MAX:
            # Вытесняем старые
            while len(_badge_cache) > _BADGE_CACHE_MAX:
                _badge_cache.popitem(last=False)

    return result


async def award_badge(tg_id: int, badge_id: str, awarded_at: int) -> None:
    """Записывает значок в БД."""
    _invalidate_badges(tg_id)
    async with db() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO user_badges (tg_id, badge_id, awarded_at) VALUES (?, ?, ?)
            """,
            (tg_id, badge_id, awarded_at),
        )


async def get_user_stats(tg_id: int) -> dict:
    """Возвращает все статистики пользователя одним запросом."""
    async with db() as conn:
        cursor = await conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM matches WHERE a_id = ? OR b_id = ?) as matches,
                (SELECT COUNT(*) FROM likes WHERE from_id = ? AND is_like = 1) as likes_sent,
                (SELECT COUNT(*) FROM reports WHERE from_id = ?) as reports_sent,
                (SELECT COUNT(*) FROM likes WHERE from_id = ? AND is_like = 1 AND message IS NOT NULL) as msglikes
        """, (tg_id, tg_id, tg_id, tg_id, tg_id))
        row = await cursor.fetchone()
        return {
            "matches": row["matches"] if row else 0,
            "likes_sent": row["likes_sent"] if row else 0,
            "reports_sent": row["reports_sent"] if row else 0,
            "msglikes": row["msglikes"] if row else 0,
        }
