"""Репозиторий фотогалереи пользователя.

position = 0 — главное фото (совпадает с users.photo_id),
position > 0 — дополнительные фото.

PERF: photo_count() кэшируется на 15 секунд — часто вызывается в browse/profile.
"""
import time
from collections import OrderedDict

from database.connection import db
from data.constants import Photo

# TTL-кэш для photo_count
_photo_count_cache: OrderedDict[int, tuple[int, float]] = OrderedDict()
_PHOTO_CACHE_TTL = 15
_PHOTO_CACHE_MAX = 500


def _invalidate_photo_count(tg_id: int) -> None:
    """Сбрасывает кэш photo_count после изменения фото."""
    _photo_count_cache.pop(tg_id, None)


async def add_photo(tg_id: int, photo_id: str) -> None:
    """Добавляет дополнительное фото в следующую свободную позицию."""
    _invalidate_photo_count(tg_id)
    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM photos WHERE tg_id = $1",
            tg_id,
        )
        pos = row["pos"] if row else 0
        if pos > Photo.MAX_EXTRA:
            return
        await conn.execute(
            """
            INSERT INTO photos (tg_id, photo_id, position)
            VALUES ($1, $2, $3)
            ON CONFLICT (tg_id, position) DO UPDATE SET photo_id = EXCLUDED.photo_id
            """,
            tg_id, photo_id, pos,
        )


async def get_photos(tg_id: int) -> list[dict]:
    """Все фото пользователя по возрастанию позиции (0 — главное)."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT id, tg_id, photo_id, position FROM photos WHERE tg_id = $1 ORDER BY position ASC",
            tg_id,
        )
        return [dict(r) for r in rows]


async def photo_count(tg_id: int) -> int:
    """Количество фото в галерее (с TTL-кэшем)."""
    now = time.monotonic()
    cached = _photo_count_cache.get(tg_id)
    if cached is not None:
        count, cached_at = cached
        if now - cached_at < _PHOTO_CACHE_TTL:
            _photo_count_cache.move_to_end(tg_id)
            return count

    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM photos WHERE tg_id = $1",
            tg_id,
        )
        result = row["c"] if row else 0

    _photo_count_cache[tg_id] = (result, now)
    if len(_photo_count_cache) > _PHOTO_CACHE_MAX:
        _photo_count_cache.popitem(last=False)
    return result


async def remove_photo(tg_id: int, position: int) -> None:
    """Удаляет фото по позиции и переиндексирует оставшиеся."""
    _invalidate_photo_count(tg_id)
    async with db() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM photos WHERE tg_id = $1 AND position = $2",
                tg_id, position,
            )
            await conn.execute(
                "UPDATE photos SET position = position - 1 WHERE tg_id = $1 AND position > $2",
                tg_id, position,
            )


async def sync_photos_to_gallery(tg_id: int) -> None:
    """Гарантирует, что главное фото из users.photo_id лежит в galleries как position 0."""
    _invalidate_photo_count(tg_id)
    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT photo_id FROM users WHERE tg_id = $1",
            tg_id,
        )
        main_photo = row["photo_id"] if row else None
        if not main_photo:
            return
        await conn.execute(
            """
            INSERT INTO photos (tg_id, photo_id, position)
            VALUES ($1, $2, 0)
            ON CONFLICT (tg_id, position) DO UPDATE SET photo_id = EXCLUDED.photo_id
            """,
            tg_id, main_photo,
        )
