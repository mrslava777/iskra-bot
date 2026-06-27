"""Репозиторий для операций с отношениями."""
from typing import Optional
from database.connection import get_db, get_single_db


async def create_relationship(user1_id: int, user2_id: int) -> None:
    a, b = sorted((user1_id, user2_id))
    conn = await get_single_db()
    try:
        await conn.execute(
            """
            INSERT INTO relationships (user1_id, user2_id, points, level, created_at)
            VALUES ($1, $2, 0, 0, EXTRACT(EPOCH FROM NOW())::INTEGER)
            ON CONFLICT (user1_id, user2_id) DO NOTHING
            """,
            a, b,
        )
    finally:
        await conn.close()


async def get_relationship(user1_id: int, user2_id: int) -> Optional[dict]:
    a, b = sorted((user1_id, user2_id))
    conn = await get_db()
    row = await conn.fetchrow(
        "SELECT * FROM relationships WHERE user1_id = $1 AND user2_id = $2",
        a, b,
    )
    return dict(row) if row else None


async def add_points(user1_id: int, user2_id: int, points: int) -> None:
    a, b = sorted((user1_id, user2_id))
    conn = await get_single_db()
    try:
        await conn.execute(
            "UPDATE relationships SET points = points + $1 WHERE user1_id = $2 AND user2_id = $3",
            points, a, b,
        )
    finally:
        await conn.close()


async def add_points_with_level_update(user1_id: int, user2_id: int, points: int) -> None:
    """Добавляет очки и обновляет уровень одной транзакцией.

    Оптимизация: вместо 2-3 запросов (add_points + get_points_and_level + update_level)
    используем 1-2 запроса с логикой уровня на стороне Python.

    Требуемый индекс:
        CREATE INDEX idx_relationships_pair ON relationships(user1_id, user2_id);
    """
    a, b = sorted((user1_id, user2_id))
    conn = await get_single_db()

    try:
        # Получаем текущие points, level и сразу обновляем points
        row = await conn.fetchrow(
            """
            UPDATE relationships SET points = points + $1
            WHERE user1_id = $2 AND user2_id = $3
            RETURNING points, level
            """,
            points, a, b,
        )

        if row:
            new_points = row["points"]
            current_level = row["level"]

            # Вычисляем новый уровень
            from data.constants import Relationship
            new_level = 0
            for i, threshold in enumerate(Relationship.THRESHOLDS):
                if new_points >= threshold:
                    new_level = i

            if new_level > current_level:
                await conn.execute(
                    "UPDATE relationships SET level = $1 WHERE user1_id = $2 AND user2_id = $3",
                    new_level, a, b,
                )
    finally:
        await conn.close()


async def get_points_and_level(user1_id: int, user2_id: int) -> Optional[tuple[int, int]]:
    a, b = sorted((user1_id, user2_id))
    conn = await get_db()
    row = await conn.fetchrow(
        "SELECT points, level FROM relationships WHERE user1_id = $1 AND user2_id = $2",
        a, b,
    )
    if not row:
        return None
    return row["points"], row["level"]


async def update_level(user1_id: int, user2_id: int, new_level: int) -> None:
    a, b = sorted((user1_id, user2_id))
    conn = await get_single_db()
    try:
        await conn.execute(
            "UPDATE relationships SET level = $1 WHERE user1_id = $2 AND user2_id = $3",
            new_level, a, b,
        )
    finally:
        await conn.close()
