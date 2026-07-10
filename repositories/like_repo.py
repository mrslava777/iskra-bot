"""Репозиторий лайков/симпатий."""
import time as _time
from database.connection import db


async def add_like(from_id: int, to_id: int, is_like: bool) -> bool:
    """Сохраняет лайк/дизлайк. Возвращает True, если возник взаимный мэтч.

    FIX (#2 race condition): устранён TOCTOU при создании мэтча.
    Раньше был check-then-insert (SELECT ... затем INSERT), из-за чего два
    почти одновременных встречных лайка могли оба пройти проверку и либо
    создать дубль, либо словить исключение на UNIQUE(a_id,b_id).
    Теперь:
      - мэтч создаётся через INSERT ... ON CONFLICT DO NOTHING, а факт
        реальной вставки определяется по total_changes → matched выставляется
        ровно один раз, без гонки;
      - рейтинг цели поднимается ТОЛЬКО когда лайк реально новый или сменился
        с дизлайка на лайк (сравниваем предыдущее состояние), чтобы повторный
        лайк не накручивал счётчик.
    """
    now = int(_time.time())
    async with db() as conn:
        # Предыдущее состояние лайка (для корректного инкремента рейтинга)
        cur_prev = await conn.execute(
            "SELECT is_like FROM likes WHERE from_id = ? AND to_id = ?",
            (from_id, to_id),
        )
        prev = await cur_prev.fetchone()
        prev_is_like = bool(prev[0]) if prev else None

        # Upsert лайка/дизлайка
        await conn.execute(
            """
            INSERT INTO likes (from_id, to_id, is_like, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (from_id, to_id) DO UPDATE SET
                is_like = excluded.is_like,
                created_at = excluded.created_at
            """,
            (from_id, to_id, 1 if is_like else 0, now),
        )

        matched = False
        if is_like:
            # Рейтинг поднимаем только если это НОВАЯ симпатия
            # (не было записи вообще, либо раньше был дизлайк).
            if prev_is_like is not True:
                await conn.execute(
                    "UPDATE users SET rating = rating + 1 WHERE tg_id = ?",
                    (to_id,),
                )

            # Есть ли встречный лайк?
            cur = await conn.execute(
                "SELECT 1 FROM likes WHERE from_id = ? AND to_id = ? AND is_like = 1",
                (to_id, from_id),
            )
            if await cur.fetchone():
                a, b = sorted((from_id, to_id))
                # Атомарно: вставляем мэтч, если его ещё нет.
                # matched = True только если строка реально добавилась.
                before = conn.total_changes
                await conn.execute(
                    """
                    INSERT INTO matches (a_id, b_id, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (a_id, b_id) DO NOTHING
                    """,
                    (a, b, now),
                )
                matched = conn.total_changes > before

        return matched


async def incoming_likes(tg_id: int) -> list[dict]:
    """Анкеты тех, кто лайкнул пользователя, но ещё без ответа от него."""
    async with db() as conn:
        cursor = await conn.execute(
            """
            SELECT u.*
            FROM likes l
            JOIN users u ON u.tg_id = l.from_id
            WHERE l.to_id = ?
              AND l.is_like = 1
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM likes l2
                  WHERE l2.from_id = ? AND l2.to_id = l.from_id
              )
            ORDER BY l.created_at DESC
            """,
            (tg_id, tg_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
