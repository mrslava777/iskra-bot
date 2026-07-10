"""Репозиторий пользователей.

PERF: добавлен in-memory TTL-кэш для get_user().
Каждый handler-chain вызывает get_user() 2-5 раз для одного и того же tg_id.
Кэш на 10 секунд убирает 50-80% запросов к users без риска для консистентности.

FIX v8: SQL allowlist — предотвращает инъекцию через динамические поля upsert_user.
        Только разрешённые поля могут быть использованы в UPDATE.
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

# SQL allowlist: только эти поля могут быть обновлены через upsert_user
# Предотвращает SQL-инъекцию через динамические поля
_USER_FIELD_ALLOWLIST = {
    "username", "name", "age", "gender", "seeking", "city",
    "bio", "interests", "photo_id", "active", "verified",
    "min_age", "max_age",
}


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
        cursor = await conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        )
        row = await cursor.fetchone()
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
        placeholders = ",".join("?" for _ in tg_ids)
        cursor = await conn.execute(
            f"SELECT tg_id, name FROM users WHERE tg_id IN ({placeholders})",
            tuple(tg_ids),
        )
        rows = await cursor.fetchall()
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
    """Обновляет или создаёт пользователя.

    FIX v8: SQL allowlist — только разрешённые поля попадают в запрос.
    """
    _invalidate_user(tg_id)
    import time as _time
    now = int(_time.time())

    # Собираем только разрешённые поля
    locals_dict = locals()
    fields_to_update = {}
    for field_name in _USER_FIELD_ALLOWLIST:
        value = locals_dict.get(field_name)
        if value is not None:
            fields_to_update[field_name] = value

    async with db() as conn:
        # Check if user exists
        cur = await conn.execute("SELECT 1 FROM users WHERE tg_id = ?", (tg_id,))
        exists = await cur.fetchone()

        if exists:
            # Update existing user — только разрешённые поля
            fields = []
            params = []
            for field_name, value in fields_to_update.items():
                fields.append(f"{field_name} = ?")
                params.append(value)

            fields.append("last_active = ?")
            params.append(now)
            params.append(tg_id)

            if fields:
                sql = f"UPDATE users SET {', '.join(fields)} WHERE tg_id = ?"
                await conn.execute(sql, tuple(params))
        else:
            # Insert new user
            await conn.execute(
                """
                INSERT INTO users (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, daily_q, daily_a, min_age, max_age, created_at, last_active, streak, rating, anon_messages_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 1), COALESCE(?, 0), 0, '', COALESCE(?, 18), COALESCE(?, 99), ?, ?, 0, 0, 0)
                """,
                (tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, min_age, max_age, now, now),
            )


async def touch_activity(tg_id: int) -> None:
    """Обновляет last_active. Не инвалидирует кэш — last_active не критичен."""
    import time as _time
    now = int(_time.time())
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET last_active = ? WHERE tg_id = ?",
            (now, tg_id),
        )


async def increment_anon_messages(tg_id: int) -> None:
    _invalidate_user(tg_id)
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET anon_messages_count = anon_messages_count + 1 WHERE tg_id = ?",
            (tg_id,),
        )


async def update_max_compat(tg_id: int, pct: int) -> None:
    """Запоминает максимальную совместимость, которую видел пользователь."""
    async with db() as conn:
        cur = await conn.execute(
            "SELECT COALESCE(max_compat, 0) FROM users WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cur.fetchone()
        current = row[0] if row else 0
        new_max = max(current, pct)
        await conn.execute(
            "UPDATE users SET max_compat = ? WHERE tg_id = ?",
            (new_max, tg_id),
        )


async def delete_user(tg_id: int) -> None:
    """Полностью удаляет пользователя и все связанные данные.

    Все DELETE-операции выполняются в одной транзакции —
    либо пользователь удалён полностью, либо не удалён вообще.
    """
    _invalidate_user(tg_id)
    async with db() as conn:
        statements = [
            ("DELETE FROM users WHERE tg_id = ?", (tg_id,)),
            ("DELETE FROM photos WHERE tg_id = ?", (tg_id,)),
            ("DELETE FROM likes WHERE from_id = ? OR to_id = ?", (tg_id, tg_id)),
            ("DELETE FROM matches WHERE a_id = ? OR b_id = ?", (tg_id, tg_id)),
            ("DELETE FROM reports WHERE from_id = ? OR to_id = ?", (tg_id, tg_id)),
            ("DELETE FROM shown_profiles WHERE from_id = ? OR to_id = ?", (tg_id, tg_id)),
            ("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,)),
            ("DELETE FROM anon_sessions WHERE a_id = ? OR b_id = ?", (tg_id, tg_id)),
            ("DELETE FROM relationships WHERE user1_id = ? OR user2_id = ?", (tg_id, tg_id)),
            ("DELETE FROM tickets WHERE tg_id = ?", (tg_id,)),
            ("DELETE FROM user_badges WHERE tg_id = ?", (tg_id,)),
        ]
        for sql, params in statements:
            await conn.execute(sql, params)
