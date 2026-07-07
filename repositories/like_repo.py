"""Репозиторий лайков/симпатий."""
import time as _time
from database.connection import db


async def add_like(from_id: int, to_id: int, is_like: bool) -> bool:
    """Сохраняет лайк/дизлайк. Возвращает True, если возник взаимный мэтч.

    Все операции (лайк, рейтинг, проверка встречного, создание мэтча)
    выполняются в одной транзакции — атомарно.
    """
    now = int(_time.time())
    async with db() as conn:
        # Upsert-like: insert or replace
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
            # Поднимаем рейтинг (число входящих симпатий) цели.
            await conn.execute(
                "UPDATE users SET rating = rating + 1 WHERE tg_id = ?",
                (to_id,),
            )
            # Проверяем встречный лайк.
            cur = await conn.execute(
                "SELECT 1 FROM likes WHERE from_id = ? AND to_id = ? AND is_like = 1",
                (to_id, from_id),
            )
            row = await cur.fetchone()
            if row:
                a, b = sorted((from_id, to_id))
                # Check if match already exists
                cur2 = await conn.execute(
                    "SELECT 1 FROM matches WHERE a_id = ? AND b_id = ?",
                    (a, b),
                )
                exists = await cur2.fetchone()
                if not exists:
                    await conn.execute(
                        """
                        INSERT INTO matches (a_id, b_id, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (a, b, now),
                    )
                    matched = True

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
