"""Репозиторий анонимного чата: очередь, сессии и раскрытие анкет."""
import asyncio
import time
from typing import Optional

from database.connection import db

# Сериализует изменения очереди/сессий внутри процесса. BEGIN IMMEDIATE ниже
# дополнительно обеспечивает атомарность на уровне SQLite.
_anon_lock = asyncio.Lock()


async def _active_session_row(conn, tg_id: int) -> Optional[dict]:
    cursor = await conn.execute(
        """
        SELECT id, a_id, b_id, a_reveal, b_reveal, started_at
        FROM anon_sessions
        WHERE ended_at IS NULL AND (a_id = ? OR b_id = ?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (tg_id, tg_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def anon_active_partner(tg_id: int) -> Optional[int]:
    async with db(write=False) as conn:
        row = await _active_session_row(conn, tg_id)
        if not row:
            return None
        return row["b_id"] if row["a_id"] == tg_id else row["a_id"]


async def anon_in_queue(tg_id: int) -> bool:
    async with db(write=False) as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM anon_queue WHERE tg_id = ?",
            (tg_id,),
        )
        return await cursor.fetchone() is not None


async def anon_find_or_queue(tg_id: int) -> tuple[str, Optional[int]]:
    """Атомарно находит собеседника или ставит пользователя в очередь."""
    now = int(time.time())

    async with _anon_lock:
        async with db() as conn:
            await conn.execute("BEGIN IMMEDIATE")

            existing = await _active_session_row(conn, tg_id)
            if existing:
                partner = (
                    existing["b_id"]
                    if existing["a_id"] == tg_id
                    else existing["a_id"]
                )
                return "in_session", partner

            cursor = await conn.execute(
                "SELECT 1 FROM anon_queue WHERE tg_id = ?",
                (tg_id,),
            )
            if await cursor.fetchone():
                return "waiting", None

            # Не берём пользователя, который уже оказался в активной сессии
            # из-за старых данных или другого процесса.
            cursor = await conn.execute(
                """
                SELECT q.tg_id
                FROM anon_queue AS q
                WHERE q.tg_id != ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM anon_sessions AS s
                      WHERE s.ended_at IS NULL
                        AND (s.a_id = q.tg_id OR s.b_id = q.tg_id)
                  )
                ORDER BY q.queued_at ASC
                LIMIT 1
                """,
                (tg_id,),
            )
            row = await cursor.fetchone()

            if row:
                partner = int(row["tg_id"])
                await conn.execute(
                    "DELETE FROM anon_queue WHERE tg_id IN (?, ?)",
                    (tg_id, partner),
                )
                await conn.execute(
                    """
                    INSERT INTO anon_sessions (
                        a_id, b_id, a_reveal, b_reveal, started_at
                    ) VALUES (?, ?, 0, 0, ?)
                    """,
                    (tg_id, partner, now),
                )
                return "matched", partner

            await conn.execute(
                """
                INSERT INTO anon_queue (tg_id, queued_at)
                VALUES (?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET queued_at = excluded.queued_at
                """,
                (tg_id, now),
            )
            return "queued", None


async def anon_leave_queue(tg_id: int) -> None:
    async with _anon_lock:
        async with db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))


async def anon_set_reveal(tg_id: int) -> Optional[dict]:
    """Совместимый низкоуровневый метод установки reveal-флага."""
    async with _anon_lock:
        async with db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            row = await _active_session_row(conn, tg_id)
            if not row:
                return None
            column = "a_reveal" if row["a_id"] == tg_id else "b_reveal"
            await conn.execute(
                f"UPDATE anon_sessions SET {column} = 1 WHERE id = ?",
                (row["id"],),
            )
            cursor = await conn.execute(
                """
                SELECT id, a_id, b_id, a_reveal, b_reveal
                FROM anon_sessions
                WHERE id = ?
                """,
                (row["id"],),
            )
            updated = await cursor.fetchone()
            return dict(updated) if updated else None


async def finalize_reveal(tg_id: int) -> dict:
    """Атомарно раскрывает пользователя и финализирует взаимное раскрытие.

    Возвращает status: ``no_session``, ``waiting`` или ``finalized``.
    При ``finalized`` в этой же транзакции создаются два лайка, мэтч и запись
    отношений. Поэтому два одновременных клика не создают дублей.
    """
    now = int(time.time())

    async with _anon_lock:
        async with db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            session = await _active_session_row(conn, tg_id)
            if not session:
                return {"status": "no_session"}

            a_id = int(session["a_id"])
            b_id = int(session["b_id"])
            partner = b_id if a_id == tg_id else a_id
            own_column = "a_reveal" if a_id == tg_id else "b_reveal"

            await conn.execute(
                f"UPDATE anon_sessions SET {own_column} = 1 "
                "WHERE id = ? AND ended_at IS NULL",
                (session["id"],),
            )
            cursor = await conn.execute(
                """
                SELECT a_reveal, b_reveal
                FROM anon_sessions
                WHERE id = ? AND ended_at IS NULL
                """,
                (session["id"],),
            )
            revealed = await cursor.fetchone()
            if not revealed:
                return {"status": "no_session"}

            if not (revealed["a_reveal"] and revealed["b_reveal"]):
                return {"status": "waiting", "partner": partner}

            # Только транзакция, которая реально закрыла активную сессию,
            # выполняет финализацию.
            cursor = await conn.execute(
                """
                UPDATE anon_sessions
                SET ended_at = ?
                WHERE id = ? AND ended_at IS NULL
                """,
                (now, session["id"]),
            )
            if cursor.rowcount != 1:
                return {"status": "no_session"}

            # Запоминаем прошлые значения, чтобы повторно не накручивать rating.
            previous: dict[tuple[int, int], Optional[bool]] = {}
            for source, target in ((a_id, b_id), (b_id, a_id)):
                old_cursor = await conn.execute(
                    "SELECT is_like FROM likes WHERE from_id = ? AND to_id = ?",
                    (source, target),
                )
                old = await old_cursor.fetchone()
                previous[(source, target)] = bool(old[0]) if old else None

                await conn.execute(
                    """
                    INSERT INTO likes (from_id, to_id, is_like, created_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(from_id, to_id) DO UPDATE SET
                        is_like = 1,
                        created_at = excluded.created_at
                    """,
                    (source, target, now),
                )

            if previous[(a_id, b_id)] is not True:
                await conn.execute(
                    "UPDATE users SET rating = rating + 1 WHERE tg_id = ?",
                    (b_id,),
                )
            if previous[(b_id, a_id)] is not True:
                await conn.execute(
                    "UPDATE users SET rating = rating + 1 WHERE tg_id = ?",
                    (a_id,),
                )

            first, second = sorted((a_id, b_id))
            await conn.execute(
                """
                INSERT INTO matches (a_id, b_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(a_id, b_id) DO NOTHING
                """,
                (first, second, now),
            )
            await conn.execute(
                """
                INSERT INTO relationships (
                    user1_id, user2_id, points, level, created_at
                ) VALUES (?, ?, 0, 0, ?)
                ON CONFLICT(user1_id, user2_id) DO NOTHING
                """,
                (first, second, now),
            )
            await conn.execute(
                "DELETE FROM anon_queue WHERE tg_id IN (?, ?)",
                (a_id, b_id),
            )

            return {
                "status": "finalized",
                "a_id": a_id,
                "b_id": b_id,
            }


async def anon_end(tg_id: int) -> Optional[int]:
    now = int(time.time())

    async with _anon_lock:
        async with db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            row = await _active_session_row(conn, tg_id)
            if row:
                partner = row["b_id"] if row["a_id"] == tg_id else row["a_id"]
                await conn.execute(
                    """
                    UPDATE anon_sessions
                    SET ended_at = ?
                    WHERE id = ? AND ended_at IS NULL
                    """,
                    (now, row["id"]),
                )
                await conn.execute(
                    "DELETE FROM anon_queue WHERE tg_id IN (?, ?)",
                    (tg_id, partner),
                )
                return int(partner)

            await conn.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))
            return None


async def anon_reveal_count(tg_id: int) -> int:
    async with db(write=False) as conn:
        cursor = await conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM anon_sessions
            WHERE (a_id = ? AND a_reveal = 1)
               OR (b_id = ? AND b_reveal = 1)
            """,
            (tg_id, tg_id),
        )
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0
