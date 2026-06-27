"""Репозиторий пользователей."""
from typing import Optional
from database.connection import get_db, get_single_db


async def get_user(tg_id: int) -> Optional[dict]:
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_names_batch(tg_ids: list[int]) -> dict[int, str]:
    """Возвращает имена пользователей batch-запросом.

    Оптимизация: вместо N запросов get_user() — один запрос с IN.
    """
    if not tg_ids:
        return {}
    conn = await get_db()
    placeholders = ",".join("?" * len(tg_ids))
    cur = await conn.execute(
        f"SELECT tg_id, name FROM users WHERE tg_id IN ({placeholders})",
        tg_ids
    )
    rows = await cur.fetchall()
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
) -> None:
    conn = await get_single_db()
    await conn.execute(
        """
        INSERT INTO users (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a, created_at, last_active, streak, rating, anon_messages_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, ''), strftime('%s','now'), strftime('%s','now'), 0, 0, 0)
        ON CONFLICT(tg_id) DO UPDATE SET
            username = COALESCE(?, username),
            name = COALESCE(?, name),
            age = COALESCE(?, age),
            gender = COALESCE(?, gender),
            seeking = COALESCE(?, seeking),
            city = COALESCE(?, city),
            bio = COALESCE(?, bio),
            interests = COALESCE(?, interests),
            photo_id = COALESCE(?, photo_id),
            active = COALESCE(?, active),
            verified = COALESCE(?, verified),
            daily_q = COALESCE(?, daily_q),
            daily_a = COALESCE(?, daily_a),
            last_active = strftime('%s','now')
        """,
        (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a,
         username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a)
    )
    await conn.commit()
    await conn.close()


async def touch_activity(tg_id: int) -> None:
    conn = await get_single_db()
    await conn.execute(
        "UPDATE users SET last_active = strftime('%s','now') WHERE tg_id = ?",
        (tg_id,)
    )
    await conn.commit()
    await conn.close()


async def increment_anon_messages(tg_id: int) -> None:
    conn = await get_single_db()
    await conn.execute(
        "UPDATE users SET anon_messages_count = anon_messages_count + 1 WHERE tg_id = ?",
        (tg_id,)
    )
    await conn.commit()
    await conn.close()
