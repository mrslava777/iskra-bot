"""Репозиторий лайков/симпатий."""
from database.connection import db


async def add_like(from_id: int, to_id: int, is_like: bool) -> bool:
    """Сохраняет лайк/дизлайк. Возвращает True, если возник взаимный мэтч.

    Все операции (лайк, рейтинг, проверка встречного, создание мэтча)
    выполняются в одной транзакции — атомарно.
    """
    async with db() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO likes (from_id, to_id, is_like, created_at)
                VALUES ($1, $2, $3, EXTRACT(EPOCH FROM NOW())::INTEGER)
                ON CONFLICT (from_id, to_id) DO UPDATE SET
                    is_like = EXCLUDED.is_like,
                    created_at = EXCLUDED.created_at
                """,
                from_id, to_id, 1 if is_like else 0,
            )

            matched = False
            if is_like:
                # Поднимаем рейтинг (число входящих симпатий) цели.
                await conn.execute(
                    "UPDATE users SET rating = rating + 1 WHERE tg_id = $1",
                    to_id,
                )
                # Проверяем встречный лайк.
                row = await conn.fetchrow(
                    "SELECT 1 FROM likes WHERE from_id = $1 AND to_id = $2 AND is_like = 1",
                    to_id, from_id,
                )
                if row:
                    a, b = sorted((from_id, to_id))
                    result = await conn.execute(
                        """
                        INSERT INTO matches (a_id, b_id, created_at)
                        VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::INTEGER)
                        ON CONFLICT (a_id, b_id) DO NOTHING
                        """,
                        a, b,
                    )
                    # asyncpg возвращает строку типа 'INSERT 0 1' или 'INSERT 0 0'
                    matched = "INSERT 0 1" in result

            return matched


async def incoming_likes(tg_id: int) -> list[dict]:
    """Анкеты тех, кто лайкнул пользователя, но ещё без ответа от него."""
    async with db() as conn:
        rows = await conn.fetch(
            """
            SELECT u.*
            FROM likes l
            JOIN users u ON u.tg_id = l.from_id
            WHERE l.to_id = $1
              AND l.is_like = 1
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM likes l2
                  WHERE l2.from_id = $2 AND l2.to_id = l.from_id
              )
            ORDER BY l.created_at DESC
            """,
            tg_id, tg_id,
        )
        return [dict(r) for r in rows]
