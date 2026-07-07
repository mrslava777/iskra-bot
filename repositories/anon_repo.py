"""Репозиторий анонимного чата («свидание вслепую») — очередь и сессии.

anon_sessions с ended_at IS NULL — активная сессия.
anon_queue — пользователи, ожидающие собеседника.
"""
from typing import Optional

from database.connection import db


async def _active_session_row(conn, tg_id: int) -> Optional[dict]:
    cursor = await conn.execute(
        """
        SELECT id, a_id, b_id, a_reveal, b_reveal
        FROM anon_sessions
        WHERE ended_at IS NULL AND (a_id = ? OR b_id = ?)
        ORDER BY id DESC LIMIT 1
        """,
        (tg_id, tg_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def anon_active_partner(tg_id: int) -> Optional[int]:
    """ID собеседника в активной сессии или None."""
    async with db() as conn:
        row = await _active_session_row(conn, tg_id)
        if not row:
            return None
        return row["b_id"] if row["a_id"] == tg_id else row["a_id"]


async def anon_in_queue(tg_id: int) -> bool:
    """Находится ли пользователь в очереди ожидания."""
    async with db() as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM anon_queue WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cursor.fetchone()
        return row is not None


async def anon_find_or_queue(tg_id: int) -> tuple[str, Optional[int]]:
    """Подбирает собеседника или ставит в очередь.

    Возвращает статус:
        in_session — уже в активной сессии (partner = ID собеседника)
        waiting    — уже стоит в очереди (partner = None)
        matched    — найден собеседник, создана сессия (partner = ID)
        queued     — поставлен в очередь, ждём (partner = None)
    """
    now = int(__import__('time').time())
    async with db() as conn:
        # Уже в сессии?
        existing = await _active_session_row(conn, tg_id)
        if existing:
            partner = existing["b_id"] if existing["a_id"] == tg_id else existing["a_id"]
            return "in_session", partner

        # Уже в очереди?
        cursor = await conn.execute("SELECT 1 FROM anon_queue WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        if row:
            return "waiting", None

        # Ищем любого другого ожидающего
        cursor = await conn.execute(
            "SELECT tg_id FROM anon_queue WHERE tg_id != ? ORDER BY queued_at ASC LIMIT 1",
            (tg_id,),
        )
        row = await cursor.fetchone()
        if row:
            partner = row["tg_id"]
            await conn.execute(
                "DELETE FROM anon_queue WHERE tg_id IN (?, ?)",
                (tg_id, partner),
            )
            await conn.execute(
                """
                INSERT INTO anon_sessions (a_id, b_id, a_reveal, b_reveal, started_at)
                VALUES (?, ?, 0, 0, ?)
                """,
                (tg_id, partner, now),
            )
            return "matched", partner

        # Никого нет — встаём в очередь.
        await conn.execute(
            "INSERT OR IGNORE INTO anon_queue (tg_id, queued_at) VALUES (?, ?)",
            (tg_id, now),
        )
        return "queued", None


async def anon_leave_queue(tg_id: int) -> None:
    """Убирает пользователя из очереди."""
    async with db() as conn:
        await conn.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))


async def anon_set_reveal(tg_id: int) -> Optional[dict]:
    """Отмечает, что пользователь раскрылся. Возвращает обновлённую сессию или None."""
    async with db() as conn:
        row = await _active_session_row(conn, tg_id)
        if not row:
            return None
        col = "a_reveal" if row["a_id"] == tg_id else "b_reveal"
        await conn.execute(
            f"UPDATE anon_sessions SET {col} = 1 WHERE id = ?",
            (row["id"],),
        )
        cursor = await conn.execute(
            "SELECT id, a_id, b_id, a_reveal, b_reveal FROM anon_sessions WHERE id = ?",
            (row["id"],),
        )
        updated = await cursor.fetchone()
        return dict(updated) if updated else None


async def anon_end(tg_id: int) -> Optional[int]:
    """Завершает активную сессию или убирает из очереди.

    Возвращает ID собеседника, если завершилась сессия, иначе None.
    """
    now = int(__import__('time').time())
    async with db() as conn:
        row = await _active_session_row(conn, tg_id)
        if row:
            await conn.execute(
                "UPDATE anon_sessions SET ended_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            return row["b_id"] if row["a_id"] == tg_id else row["a_id"]
        # Сессии нет — на всякий случай выходим из очереди.
        await conn.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))
        return None


async def anon_reveal_count(tg_id: int) -> int:
    """Сколько раз пользователь раскрывался в анонимных свиданиях (для значка revealer)."""
    async with db() as conn:
        cursor = await conn.execute(
            """
            SELECT COUNT(*) AS c FROM anon_sessions
            WHERE (a_id = ? AND a_reveal = 1) OR (b_id = ? AND b_reveal = 1)
            """,
            (tg_id, tg_id),
        )
        row = await cursor.fetchone()
        return row["c"] if row else 0
