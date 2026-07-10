"""Репозиторий фотогалереи пользователя.

position = 0 — главное фото (совпадает с users.photo_id),
position > 0 — дополнительные фото.

FIX: Добавлена обработка ошибок UNIQUE constraint, 
     улучшено логирование, исправлена логика позиций.
FIX v9: Гарантированная синхронизация users.photo_id ↔ photos(0).
        Добавлены проверки границ и информативные ошибки.
"""
import logging
import time
from collections import OrderedDict

from database.connection import db
from data.constants import Photo

log = logging.getLogger("iskra.photo_repo")

# TTL-кэш для photo_count
_photo_count_cache: OrderedDict[int, tuple[int, float]] = OrderedDict()
_PHOTO_CACHE_TTL = 15
_PHOTO_CACHE_MAX = 500


def _invalidate_photo_count(tg_id: int) -> None:
    """Сбрасывает кэш photo_count после изменения фото."""
    _photo_count_cache.pop(tg_id, None)


async def add_photo(tg_id: int, photo_id: str) -> tuple[bool, str]:
    """Добавляет дополнительное фото в следующую свободную позицию.

    FIX v9: Возвращает (success, message) вместо None.
    Проверяет границы ДО вставки, обрабатывает UNIQUE constraint.
    """
    _invalidate_photo_count(tg_id)

    async with db() as conn:
        # Сначала считаем текущее количество фото
        cursor = await conn.execute(
            """SELECT COUNT(*) AS c, COALESCE(MAX(position), -1) + 1 AS next_pos
               FROM photos WHERE tg_id = ?""",
            (tg_id,),
        )
        row = await cursor.fetchone()
        current_count = row["c"] if row else 0
        next_pos = row["next_pos"] if row and row["next_pos"] is not None else 0

        # Проверяем лимит
        if current_count >= Photo.MAX_TOTAL:
            log.warning("Photo limit reached for user %d: %d/%d", tg_id, current_count, Photo.MAX_TOTAL)
            return False, f"Достигнут лимит фото ({Photo.MAX_TOTAL}). Удалите старые фото."

        # next_pos может быть > MAX_EXTRA если есть дырки в позициях
        # Найдём первую свободную позицию
        cursor = await conn.execute(
            "SELECT position FROM photos WHERE tg_id = ? ORDER BY position",
            (tg_id,),
        )
        existing_positions = {r["position"] for r in await cursor.fetchall()}

        # Найдём первую свободную позицию от 0 до MAX_EXTRA
        pos = None
        for p in range(Photo.MAX_TOTAL):
            if p not in existing_positions:
                pos = p
                break

        if pos is None:
            log.error("No free position found for user %d despite count=%d", tg_id, current_count)
            return False, "Не удалось найти свободную позицию для фото."

        try:
            await conn.execute(
                """
                INSERT INTO photos (tg_id, photo_id, position)
                VALUES (?, ?, ?)
                ON CONFLICT (tg_id, position) DO UPDATE SET 
                    photo_id = excluded.photo_id,
                    created_at = strftime('%s','now')
                """,
                (tg_id, photo_id, pos),
            )
            log.info("Photo added for user %d at position %d", tg_id, pos)

            # Если это position 0 — обновляем users.photo_id
            if pos == 0:
                await conn.execute(
                    "UPDATE users SET photo_id = ? WHERE tg_id = ?",
                    (photo_id, tg_id),
                )
                log.info("Updated main photo for user %d", tg_id)

            return True, f"Фото добавлено! ({current_count + 1}/{Photo.MAX_TOTAL})"

        except Exception as e:
            log.error("Failed to add photo for user %d: %s", tg_id, e, exc_info=True)
            return False, "Ошибка сохранения фото. Попробуйте позже."


async def get_photos(tg_id: int) -> list[dict]:
    """Все фото пользователя по возрастанию позиции (0 — главное)."""
    async with db() as conn:
        cursor = await conn.execute(
            "SELECT id, tg_id, photo_id, position FROM photos WHERE tg_id = ? ORDER BY position ASC",
            (tg_id,),
        )
        rows = await cursor.fetchall()
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
        cursor = await conn.execute(
            "SELECT COUNT(*) AS c FROM photos WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cursor.fetchone()
        result = row["c"] if row else 0

    _photo_count_cache[tg_id] = (result, now)
    if len(_photo_count_cache) > _PHOTO_CACHE_MAX:
        _photo_count_cache.popitem(last=False)
    return result


async def remove_photo(tg_id: int, position: int) -> tuple[bool, str]:
    """Удаляет фото по позиции и переиндексирует оставшиеся.

    FIX v9: Безопасное переиндексирование — временная таблица + atomic swap.
    """
    _invalidate_photo_count(tg_id)

    async with db() as conn:
        # Проверяем существование
        cursor = await conn.execute(
            "SELECT photo_id FROM photos WHERE tg_id = ? AND position = ?",
            (tg_id, position),
        )
        if not await cursor.fetchone():
            return False, "Фото не найдено."

        try:
            # Удаляем
            await conn.execute(
                "DELETE FROM photos WHERE tg_id = ? AND position = ?",
                (tg_id, position),
            )

            # Переиндексируем: создаём временную таблицу с новыми позициями
            # Это безопаснее чем UPDATE position = position - 1 (может нарушить UNIQUE)
            cursor = await conn.execute(
                """
                SELECT photo_id FROM photos 
                WHERE tg_id = ? AND position > ? 
                ORDER BY position ASC
                """,
                (tg_id, position),
            )
            remaining = [r["photo_id"] for r in await cursor.fetchall()]

            # Удаляем все с position > удалённой
            await conn.execute(
                "DELETE FROM photos WHERE tg_id = ? AND position > ?",
                (tg_id, position),
            )

            # Вставляем обратно с новыми позициями
            for i, pid in enumerate(remaining):
                new_pos = position + i
                await conn.execute(
                    """
                    INSERT INTO photos (tg_id, photo_id, position)
                    VALUES (?, ?, ?)
                    ON CONFLICT (tg_id, position) DO UPDATE SET 
                        photo_id = excluded.photo_id
                    """,
                    (tg_id, pid, new_pos),
                )

            # Если удалили position 0 — обновляем users.photo_id
            if position == 0:
                if remaining:
                    await conn.execute(
                        "UPDATE users SET photo_id = ? WHERE tg_id = ?",
                        (remaining[0], tg_id),
                    )
                else:
                    # Нет фото вообще
                    await conn.execute(
                        "UPDATE users SET photo_id = NULL WHERE tg_id = ?",
                        (tg_id,),
                    )

            log.info("Photo removed for user %d at position %d, reindexed %d photos", 
                     tg_id, position, len(remaining))
            return True, "Фото удалено."

        except Exception as e:
            log.error("Failed to remove photo for user %d: %s", tg_id, e, exc_info=True)
            return False, "Ошибка удаления фото. Попробуйте позже."


async def sync_photos_to_gallery(tg_id: int) -> tuple[bool, str]:
    """Гарантирует, что главное фото из users.photo_id лежит в photos как position 0.

    FIX v9: Возвращает (success, message), обрабатывает ошибки.
    """
    _invalidate_photo_count(tg_id)

    async with db() as conn:
        cursor = await conn.execute(
            "SELECT photo_id FROM users WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cursor.fetchone()
        main_photo = row["photo_id"] if row else None

        if not main_photo:
            log.debug("No main photo to sync for user %d", tg_id)
            return True, "Нет главного фото для синхронизации."

        try:
            await conn.execute(
                """
                INSERT INTO photos (tg_id, photo_id, position)
                VALUES (?, ?, 0)
                ON CONFLICT (tg_id, position) DO UPDATE SET 
                    photo_id = excluded.photo_id,
                    created_at = strftime('%s','now')
                """,
                (tg_id, main_photo),
            )
            log.info("Synced main photo to gallery for user %d", tg_id)
            return True, "Главное фото синхронизировано."

        except Exception as e:
            log.error("Failed to sync photos for user %d: %s", tg_id, e, exc_info=True)
            return False, "Ошибка синхронизации фото."


async def set_main_photo(tg_id: int, photo_id: str) -> tuple[bool, str]:
    """Устанавливает главное фото (position 0) и обновляет users.photo_id.

    NEW v9: Единая точка для установки главного фото при регистрации/редактировании.
    """
    _invalidate_photo_count(tg_id)

    async with db() as conn:
        try:
            # Обновляем users.photo_id
            await conn.execute(
                "UPDATE users SET photo_id = ? WHERE tg_id = ?",
                (photo_id, tg_id),
            )

            # Синхронизируем с галереей
            await conn.execute(
                """
                INSERT INTO photos (tg_id, photo_id, position)
                VALUES (?, ?, 0)
                ON CONFLICT (tg_id, position) DO UPDATE SET 
                    photo_id = excluded.photo_id,
                    created_at = strftime('%s','now')
                """,
                (tg_id, photo_id),
            )

            log.info("Main photo set for user %d", tg_id)
            return True, "Главное фото сохранено!"

        except Exception as e:
            log.error("Failed to set main photo for user %d: %s", tg_id, e, exc_info=True)
            return False, "Ошибка сохранения главного фото."
