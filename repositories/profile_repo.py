"""Репозиторий для операций ленты анкет."""
from typing import Optional
from database.connection import get_db, get_single_db


async def next_candidate(viewer_id: int, viewer: dict | None = None) -> Optional[dict]:
    """Возвращает следующего кандидата для ленты.

    Оптимизация: используем LEFT JOIN + IS NULL вместо NOT IN подзапросов
    для лучшего использования индексов PostgreSQL.

    Требуемые индексы:
        CREATE INDEX idx_users_active_banned ON users(active, is_banned);
        CREATE INDEX idx_users_photo_name ON users(photo_id, name);
        CREATE INDEX idx_shown_profiles_from_to ON shown_profiles(from_id, to_id);
        CREATE INDEX idx_likes_from_to ON likes(from_id, to_id);
        CREATE INDEX idx_users_gender ON users(gender);
        CREATE INDEX idx_users_seeking ON users(seeking);
        CREATE INDEX idx_users_last_active ON users(last_active DESC);
    """
    conn = await get_db()
    if viewer is None:
        return None

    seeking = viewer.get("seeking", "any")
    gender = viewer.get("gender")

    query = """
        SELECT u.* FROM users u
        LEFT JOIN shown_profiles sp ON sp.from_id = $1 AND sp.to_id = u.tg_id
        LEFT JOIN likes l ON l.from_id = $2 AND l.to_id = u.tg_id
        WHERE u.tg_id != $3
          AND u.active = 1
          AND u.is_banned = 0
          AND u.photo_id IS NOT NULL
          AND u.name IS NOT NULL
          AND sp.to_id IS NULL
          AND l.to_id IS NULL
    """
    params = [viewer_id, viewer_id, viewer_id]

    if seeking and seeking != "any":
        query += " AND u.gender = $4"
        params.append(seeking)

    if gender:
        query += " AND (u.seeking = $5 OR u.seeking = 'any')"
        params.append(gender)

    # Фильтр по возрасту (предпочтения смотрящего).
    min_age = viewer.get("min_age") or 18
    max_age = viewer.get("max_age") or 99
    query += " AND u.age BETWEEN $6 AND $7"
    params.extend([min_age, max_age])

    query += " ORDER BY u.last_active DESC LIMIT 1"

    row = await conn.fetchrow(query, *params)
    return dict(row) if row else None


async def mark_shown(from_id: int, to_id: int) -> None:
    """Отмечает профиль как показанный."""
    conn = await get_single_db()
    try:
        await conn.execute(
            """
            INSERT INTO shown_profiles (from_id, to_id, shown_at)
            VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::INTEGER)
            ON CONFLICT (from_id, to_id) DO NOTHING
            """,
            from_id, to_id,
        )
    finally:
        await conn.close()
