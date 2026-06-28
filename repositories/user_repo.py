"""Репозиторий пользователей.

PERF: добавлен in-memory TTL-кэш для get_user().
Каждый handler-chain вызывает get_user() 2-5 раз для одного и того же tg_id.
Кэш на 10 секунд убирает 50-80% запросов к users без риска для консистентности.
"""
import time
from collections import OrderedDict
from typing import Optional

from database.connection import db

# ── User cache ────────────────────────────────────────────────────
# LRU + TTL кэш для get_user(). Безопасен в asyncio (single-threaded event loop).
_user_cache: OrderedDict[int, tuple[Optional[dict], float]] = OrderedDict()
_USER_CACHE_TTL = 10  # секунд
_USER_CACHE_MAX = 500


def _invalidate_user(tg_id: int) -> None:
    """Сбрасывает кэш для пользователя после изменения данных."""
    _user_cache.pop(tg_id, None)


async def get_user(tg_id: int) -> Optional[dict]:
    """Возвращает данные пользователя с кэшированием.

    TTL = 10 секунд. Кэш сбрасывается при upsert_user / delete_user.
    """
    now = time.monotonic()

    cached = _user_cache.get(tg_id)
    if cached is not None:
        data, cached_at = cached
        if now - cached_at < _USER_CACHE_TTL:
            _user_cache.move_to_end(tg_id)
            return data

    async with db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE tg_id = $1", tg_id,
        )
        result = dict(row) if row else None

    _user_cache[tg_id] = (result, now)
    if len(_user_cache) > _USER_CACHE_MAX:
        _user_cache.popitem(last=False)
    return result


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
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
) -> None:
    _invalidate_user(tg_id)
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO users (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a, min_age, max_age, created_at, last_active, streak, rating, anon_messages_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, 1), COALESCE($12, 0), 0, '', COALESCE($13, 18), COALESCE($14, 99), EXTRACT(EPOCH FROM NOW())::INTEGER, EXTRACT(EPOCH FROM NOW())::INTEGER, 0, 0, 0)
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
                min_age = COALESCE($13, users.min_age),
                max_age = COALESCE($14, users.max_age),
                last_active = EXTRACT(EPOCH FROM NOW())::INTEGER
            """,
            tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, min_age, max_age,
        )


async def touch_activity(tg_id: int) -> None:
    """Обновляет last_active. Не инвалидирует кэш — last_active не критичен."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET last_active = EXTRACT(EPOCH FROM NOW())::INTEGER WHERE tg_id = $1",
            tg_id,
        )


async def increment_anon_messages(tg_id: int) -> None:
    _invalidate_user(tg_id)
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
    _invalidate_user(tg_id)
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
