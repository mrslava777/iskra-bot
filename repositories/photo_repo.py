"""Репозиторий фотогалереи пользователя.

position = 0 — главное фото (совпадает с users.photo_id),
position > 0 — дополнительные фото.
"""
from database.connection import db, get_single_db
from data.constants import Photo


async def add_photo(tg_id: int, photo_id: str) -> None:
    """Добавляет дополнительное фото в следующую свободную позицию."""
    conn = await get_single_db()
    try:
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
    finally:
        await conn.close()


async def get_photos(tg_id: int) -> list[dict]:
    """Все фото пользователя по возрастанию позиции (0 — главное)."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT id, tg_id, photo_id, position FROM photos WHERE tg_id = $1 ORDER BY position ASC",
            tg_id,
        )
        return [dict(r) for r in rows]


async def photo_count(tg_id: int) -> int:
    """Количество фото в галерее."""
    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM photos WHERE tg_id = $1",
            tg_id,
        )
        return row["c"] if row else 0


async def remove_photo(tg_id: int, position: int) -> None:
    """Удаляет фото по позиции и переиндексирует оставшиеся."""
    conn = await get_single_db()
    try:
        await conn.execute(
            "DELETE FROM photos WHERE tg_id = $1 AND position = $2",
            tg_id, position,
        )
        # Переиндексация: собираем оставшиеся и раскладываем по 0..N.
        rows = await conn.fetch(
            "SELECT photo_id FROM photos WHERE tg_id = $1 ORDER BY position ASC",
            tg_id,
        )
        remaining = [r["photo_id"] for r in rows]
        await conn.execute("DELETE FROM photos WHERE tg_id = $1", tg_id)
        for i, pid in enumerate(remaining):
            await conn.execute(
                "INSERT INTO photos (tg_id, photo_id, position) VALUES ($1, $2, $3)",
                tg_id, pid, i,
            )
    finally:
        await conn.close()


async def sync_photos_to_gallery(tg_id: int) -> None:
    """Гарантирует, что главное фото из users.photo_id лежит в galleries как position 0."""
    conn = await get_single_db()
    try:
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
    finally:
        await conn.close()
