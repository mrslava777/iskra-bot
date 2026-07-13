"""Репозиторий анонимного чата («свидание вслепую») — очередь и сессии.

anon_sessions с ended_at IS NULL — активная сессия.
anon_queue — пользователи, ожидающие собеседника.

FIX (#5 транзакционность reveal): добавлена finalize_reveal() — атомарно
 в ОДНОЙ транзакции ставит флаг раскрытия, и если раскрылись оба:
 завершает сессию (UPDATE ... WHERE ended_at IS NULL), создаёт встречные
 лайки, мэтч и запись relationship. Завершение через total_changes
 гарантирует, что финализацию выполнит ровно один клиент, даже если оба
 нажали «Открыться» одновременно — нет двойного announce_match и полу-записей.
FIX (#8 __import__): убраны inline __import__('time'), импорт вынесен наверх.
FIX (race condition matching): anon_find_or_queue() теперь использует
 BEGIN IMMEDIATE — эксклюзивная блокировка с первой инструкции. Это
 предотвращает ситуацию, когда два пользователя одновременно выбирают
 одного и того же партнёра из очереди. Раньше SELECT шёл без блокировки
 (DEFERRED), и оба конкурентных await-точки могли прочитать одну строку
 до того, как кто-либо успел DELETE.
FIX (race condition reveal): finalize_reveal() теперь тоже BEGIN IMMEDIATE.
 Без этого оба одновременных вызова могли видеть ended_at IS NULL в своём
 снапшоте, оба проходили проверку total_changes, и оба создавали дубли
 лайков/мэтчей/relationship.
FIX (DB-level duplicate protection): триггеры + partial unique indexes на
 anon_sessions гарантируют, что у пользователя не может быть двух активных
 сессий — даже при деплое на Railway с несколькими контейнерами.
 При попытке создать дубль ловим IntegrityError и возвращаем in_session.
"""
import sqlite3
import time as _time
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

    FIX (DB-level protection): если триггер/индекс блокирует INSERT
    (кто-то из участников уже в активной сессии — возможно, в другом
    контейнере), ловим IntegrityError и возвращаем in_session.
    """
    now = int(_time.time())
    async with db() as conn:
        # FIX (race): BEGIN IMMEDIATE — эксклюзивная блокировка сразу.
        # Без этого две конкурентные корутины могли одновременно прочитать
        # одного и того же партнёра из очереди (DEFERRED tx даёт shared lock
        # на чтение), и оба создали бы сессии с одним человеком.
        await conn.execute("BEGIN IMMEDIATE")

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
            try:
                await conn.execute(
                    """
                    INSERT INTO anon_sessions (a_id, b_id, a_reveal, b_reveal, started_at)
                    VALUES (?, ?, 0, 0, ?)
                    """,
                    (tg_id, partner, now),
                )
            except sqlite3.IntegrityError:
                # Триггер или partial unique index сработал:
                # кто-то из участников уже в активной сессии (возможно,
                # созданной параллельным контейнером между нашим SELECT и INSERT).
                # Возвращаем in_session — пользователь увидит существующую сессию.
                # Партнёра возвращаем в очередь, если он был удалён.
                await conn.execute(
                    "INSERT OR IGNORE INTO anon_queue (tg_id, queued_at) VALUES (?, ?)",
                    (partner, now),
                )
                # Находим существующую сессию пользователя
                existing = await _active_session_row(conn, tg_id)
                if existing:
                    partner = existing["b_id"] if existing["a_id"] == tg_id else existing["a_id"]
                    return "in_session", partner
                return "in_session", None
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
    """Отмечает, что пользователь раскрылся. Возвращает обновлённую сессию или None.

    Оставлено для обратной совместимости. Для завершённого сценария «оба
    раскрылись» используйте finalize_reveal() — она атомарна.
    """
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


async def finalize_reveal(tg_id: int) -> dict:
    """Атомарно обрабатывает нажатие «Открыться».

    Всё в ОДНОЙ транзакции:
      1) ставит флаг раскрытия текущему пользователю;
      2) перечитывает флаги;
      3) если раскрылись оба — завершает сессию через
         UPDATE ... WHERE ended_at IS NULL и по total_changes определяет,
         кто реально её закрыл. Только этот вызов создаёт встречные лайки,
         мэтч и relationship и получает status="finalized".

    Возвращает dict со status:
      no_session   — активной сессии нет;
      waiting      — раскрылся только текущий, ждём собеседника (partner);
      finalized    — раскрылись оба, всё создано (a_id, b_id, partner, is_new_match);
      already_done — оба раскрыты, но финализацию уже выполнил собеседник.
    """
    now = int(_time.time())
    async with db() as conn:
        # FIX (race): BEGIN IMMEDIATE — эксклюзивная блокировка сразу.
        # Без этого два одновременных вызова могли видеть ended_at IS NULL
        # в своём DEFERRED-снапшоте, оба проходили проверку total_changes,
        # и оба создавали дубли лайков/мэтчей/relationship.
        await conn.execute("BEGIN IMMEDIATE")

        row = await _active_session_row(conn, tg_id)
        if not row:
            return {"status": "no_session"}

        sid = row["id"]
        a_id, b_id = row["a_id"], row["b_id"]
        partner = b_id if a_id == tg_id else a_id

        col = "a_reveal" if a_id == tg_id else "b_reveal"
        await conn.execute(
            f"UPDATE anon_sessions SET {col} = 1 WHERE id = ?",
            (sid,),
        )

        cur = await conn.execute(
            "SELECT a_reveal, b_reveal FROM anon_sessions WHERE id = ?",
            (sid,),
        )
        flags = await cur.fetchone()
        both = bool(flags["a_reveal"]) and bool(flags["b_reveal"])

        if not both:
            return {"status": "waiting", "partner": partner}

        # Оба раскрылись — пытаемся завершить сессию атомарно.
        before = conn.total_changes
        await conn.execute(
            "UPDATE anon_sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (now, sid),
        )
        if conn.total_changes == before:
            # Сессию уже завершил собеседник — финализацию делать не нам.
            return {"status": "already_done", "partner": partner}

        # Встречные лайки (idempotent).
        await conn.execute(
            """
            INSERT INTO likes (from_id, to_id, is_like, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT (from_id, to_id) DO UPDATE SET is_like = 1, created_at = excluded.created_at
            """,
            (a_id, b_id, now),
        )
        await conn.execute(
            """
            INSERT INTO likes (from_id, to_id, is_like, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT (from_id, to_id) DO UPDATE SET is_like = 1, created_at = excluded.created_at
            """,
            (b_id, a_id, now),
        )

        # Мэтч (idempotent) + факт новизны.
        m_a, m_b = sorted((a_id, b_id))
        mbefore = conn.total_changes
        await conn.execute(
            """
            INSERT INTO matches (a_id, b_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT (a_id, b_id) DO NOTHING
            """,
            (m_a, m_b, now),
        )
        is_new_match = conn.total_changes > mbefore

        # Relationship (idempotent).
        r_a, r_b = sorted((a_id, b_id))
        await conn.execute(
            """
            INSERT INTO relationships (user1_id, user2_id, points, level, created_at)
            VALUES (?, ?, 0, 0, ?)
            ON CONFLICT (user1_id, user2_id) DO NOTHING
            """,
            (r_a, r_b, now),
        )

        return {
            "status": "finalized",
            "a_id": a_id,
            "b_id": b_id,
            "partner": partner,
            "is_new_match": is_new_match,
        }


async def anon_end(tg_id: int) -> Optional[int]:
    """Завершает активную сессию или убирает из очереди.

    Возвращает ID собеседника, если завершилась сессия, иначе None.
    """
    now = int(_time.time())
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
