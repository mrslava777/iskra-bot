"""Репозиторий для операций ленты анкет.

FIX: next_candidate использует стабильный набор параметров ($1..$7) независимо
     от фильтров — лучше для кэша prepared statements asyncpg.
"""
from typing import Optional

from database.connection import db


async def next_candidate(viewer_id: int, viewer: dict | None = None) -> Optional[dict]:
    """Возвращает следующего кандидата для ленты.

    FIX: вместо динамического набора параметров ($4, $5, $6, $7 в зависимости
    от фильтров) — всегда передаём фиксированные 7 параметров.
    Это позволяет asyncpg кэшировать один prepared statement вместо нескольких.
    Фильтры по gender/seeking применяются условно в SQL через OR с флагом.

    Требуемые индексы:
        CREATE INDEX idx_users_active_banned ON users(active, is_banned);
        CREATE INDEX idx_shown_profiles_from_to ON shown_profiles(from_id, to_id);
        CREATE INDEX idx_likes_from_to ON likes(from_id, to_id);
        CREATE INDEX idx_users_gender ON users(gender);
        CREATE INDEX idx_users_seeking ON users(seeking);
        CREATE INDEX idx_users_last_active ON users(last_active DESC);
    """
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender", "")
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99

    async with db() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.* FROM users u
            LEFT JOIN shown_profiles sp ON sp.from_id = $1 AND sp.to_id = u.tg_id
            LEFT JOIN likes l ON l.from_id = $1 AND l.to_id = u.tg_id
            WHERE u.tg_id != $1
              AND u.active = 1
              AND u.is_banned = 0
              AND u.photo_id IS NOT NULL
              AND u.name IS NOT NULL
              AND sp.to_id IS NULL
              AND l.to_id IS NULL
              AND ($2 = 'any' OR u.gender = $2)
              AND ($3 = '' OR u.seeking = $3 OR u.seeking = 'any')
              AND u.age BETWEEN $4 AND $5
            ORDER BY u.last_active DESC
            LIMIT 1
            """,
            viewer_id, seeking, gender, min_age, max_age,
        )
        return dict(row) if row else None


async def mark_shown(from_id: int, to_id: int) -> None:
    """Отмечает профиль как показанный."""
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO shown_profiles (from_id, to_id, shown_at)
            VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::INTEGER)
            ON CONFLICT (from_id, to_id) DO NOTHING
            """,
            from_id, to_id,
        )


async def cleanup_shown_profiles(max_age_days: int = 30) -> int:
    """Удаляет записи shown_profiles старше max_age_days дней.

    FIX: без этой очистки таблица shown_profiles растёт бесконечно.
    Рекомендуется вызывать периодически (раз в сутки) из cron или startup.
    Возвращает количество удалённых записей.
    """
    import time
    cutoff = int(time.time()) - max_age_days * 86400
    async with db() as conn:
        result = await conn.execute(
            "DELETE FROM shown_profiles WHERE shown_at < $1 AND shown_at > 0",
            cutoff,
        )
        # result is like "DELETE 1234"
        count = int(result.split()[-1]) if result else 0
        return count
