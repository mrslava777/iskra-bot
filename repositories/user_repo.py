"""Репозиторий пользователей."""
from typing import Optional

from database.connection import db


async def get_user(tg_id: int) -> Optional[dict]:
    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE tg_id = $1", tg_id,
        )
        return dict(row) if row else None


async def get_user_names_batch(tg_ids: list[int]) -> dict[int, str]:
    """Возвращает имена пользователей batch-запросом."""
    if not tg_ids:
        return {}
    async with db() as conn:
        placeholders = ",".join(f"${i+1}" for i in range(len(tg_ids)))
        rows = await conn.fetch(
            f"SELECT tg_id, name FROM users WHERE tg_id IN ({placeholders})",
            *tg_ids,
        )
        return {r["tg_id"]: r["name"] or f"ID:{r['tg_id']}" for r in rows}


async def upsert_user(
    tg_id: int,
    username: Optional[str] = None,
    name: Optional[str] = None,
    age: Optional[int] = None,
    gender: Optional[str] = None,
    seeking: Optional[str] = None,
    city: Optional[str] = None,
    bio: Optional[str] = None,
    interests: Optional[str] = None,
    photo_id: Optional[str] = None,
    active: Optional[int] = None,
    verified: Optional[int] = None,
    daily_q: Optional[int] = None,
    daily_a: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
) -> None:
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO users (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a, min_age, max_age, created_at, last_active, streak, rating, anon_messages_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, 1), COALESCE($12, 0), COALESCE($13, 0), COALESCE($14, ''), COALESCE($15, 18), COALESCE($16, 99), EXTRACT(EPOCH FROM NOW())::INTEGER, EXTRACT(EPOCH FROM NOW())::INTEGER, 0, 0, 0)
            ON CONFLICT (tg_id) DO UPDATE SET
                username = COALESCE($2, users.username),
                name = COALESCE($3, users.name),
                age = COALESCE($4, users.age),
                gender = COALESCE($5, users.gender),
                seeking = COALESCE($6, users.seeking),
                city = COALESCE($7, users.city),
                bio = COALESCE($8, users.bio),
                interests = COALESCE($9, users.interests),
                photo_id = COALESCE($10, users.photo_id),
                active = COALESCE($11, users.active),
                verified = COALESCE($12, users.verified),
                daily_q = COALESCE($13, users.daily_q),
                daily_a = COALESCE($14, users.daily_a),
                min_age = COALESCE($15, users.min_age),
                max_age = COALESCE($16, users.max_age),
                last_active = EXTRACT(EPOCH FROM NOW())::INTEGER
            """,
            tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a, min_age, max_age,
        )


async def touch_activity(tg_id: int) -> None:
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET last_active = EXTRACT(EPOCH FROM NOW())::INTEGER WHERE tg_id = $1",
            tg_id,
        )


async def increment_anon_messages(tg_id: int) -> None:
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET anon_messages_count = anon_messages_count + 1 WHERE tg_id = $1",
            tg_id,
        )


async def update_max_compat(tg_id: int, pct: int) -> None:
    """Запоминает максимальную совместимость, которую видел пользователь."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET max_compat = GREATEST(COALESCE(max_compat, 0), $1) WHERE tg_id = $2",
            pct, tg_id,
        )


async def delete_user(tg_id: int) -> None:
    """Полностью удаляет пользователя и все связанные данные.

    Все DELETE-операции выполняются в одной транзакции —
    либо пользователь удалён полностью, либо не удалён вообще.
    """
    async with db() as conn:
        async with conn.transaction():
            statements = [
                ("DELETE FROM users WHERE tg_id = $1", (tg_id,)),
                ("DELETE FROM photos WHERE tg_id = $1", (tg_id,)),
                ("DELETE FROM likes WHERE from_id = $1 OR to_id = $1", (tg_id,)),
                ("DELETE FROM matches WHERE a_id = $1 OR b_id = $1", (tg_id,)),
                ("DELETE FROM reports WHERE from_id = $1 OR to_id = $1", (tg_id,)),
                ("DELETE FROM shown_profiles WHERE from_id = $1 OR to_id = $1", (tg_id,)),
                ("DELETE FROM anon_queue WHERE tg_id = $1", (tg_id,)),
                ("DELETE FROM anon_sessions WHERE a_id = $1 OR b_id = $1", (tg_id,)),
                ("DELETE FROM relationships WHERE user1_id = $1 OR user2_id = $1", (tg_id,)),
                ("DELETE FROM tickets WHERE tg_id = $1", (tg_id,)),
                ("DELETE FROM user_badges WHERE tg_id = $1", (tg_id,)),
            ]
            for sql, params in statements:
                await conn.execute(sql, *params)
