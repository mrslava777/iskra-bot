"""Сервис уровней отношений между пользователями."""
import time
from typing import Optional

import database as db


# Уровни отношений
LEVELS = [
    (0, "💛 Симпатия", 10),
    (1, "🧡 Общение", 30),
    (2, "❤️ Интерес", 60),
    (3, "💖 Близость", 100),
    (4, "💞 Пара", 999999),  # max
]

# Лимиты
MAX_DAILY_POINTS = 20
MIN_MESSAGE_INTERVAL = 120  # 2 минуты
STREAK_BONUS_24H = 5
STREAK_BONUS_2DAYS = 10
STREAK_BONUS_5DAYS = 20
# Штрафы за тишину отключены по просьбе владельца (наказывали за возвращение).


def _normalize_pair(a: int, b: int) -> tuple[int, int]:
    """Гарантирует user1_id < user2_id."""
    return (a, b) if a < b else (b, a)


def _now() -> int:
    return int(time.time())


def _today_start() -> int:
    now = _now()
    return now - (now % 86400)


def _level_info(level: int) -> tuple[str, int]:
    """Возвращает (название, points_needed_for_next)."""
    if level >= len(LEVELS):
        return LEVELS[-1][1], LEVELS[-1][2]
    return LEVELS[level][1], LEVELS[level][2]


def _points_for_next(level: int) -> int:
    if level >= len(LEVELS) - 1:
        return LEVELS[-1][2]
    return LEVELS[level][2]


async def get_relationship(user1_id: int, user2_id: int) -> Optional[dict]:
    """Возвращает relationship или None."""
    u1, u2 = _normalize_pair(user1_id, user2_id)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM relationships WHERE user1_id = ? AND user2_id = ?",
        (u1, u2),
    )
    row = await cur.fetchone()
    if row:
        return dict(row)
    return None


async def create_relationship_if_not_exists(user1_id: int, user2_id: int) -> dict:
    """Создаёт запись, если её нет. Возвращает relationship."""
    existing = await get_relationship(user1_id, user2_id)
    if existing:
        return existing
    u1, u2 = _normalize_pair(user1_id, user2_id)
    conn = await db.get_db()
    now = _now()
    await conn.execute(
        """INSERT INTO relationships
           (user1_id, user2_id, level, points, last_message_at, created_at)
           VALUES (?, ?, 0, 0, ?, ?)""",
        (u1, u2, now, now),
    )
    await conn.commit()
    return await get_relationship(user1_id, user2_id)


async def add_message_event(user_from: int, user_to: int) -> dict:
    """Обрабатывает сообщение между пользователями. Возвращает обновлённый relationship."""
    # Проверяем, есть ли мэтч
    conn = await db.get_db()
    a, b = sorted((user_from, user_to))
    cur = await conn.execute(
        "SELECT 1 FROM matches WHERE a_id = ? AND b_id = ?",
        (a, b),
    )
    if not await cur.fetchone():
        return None  # Нет мэтча — нет прогресса

    rel = await create_relationship_if_not_exists(user_from, user_to)
    u1, u2 = _normalize_pair(user_from, user_to)
    now = _now()

    # Проверяем интервал (не чаще 2 минут)
    last_msg = rel.get("last_message_at") or 0
    if now - last_msg < MIN_MESSAGE_INTERVAL:
        return rel  # Слишком быстро, игнорируем

    # Проверяем дневной лимит
    today = _today_start()
    cur = await conn.execute(
        """SELECT COALESCE(SUM(delta), 0) AS daily_sum
           FROM relationship_events
           WHERE pair_u1 = ? AND pair_u2 = ? AND day_start = ?""",
        (u1, u2, today),
    )
    row = await cur.fetchone()
    daily_sum = row["daily_sum"] if row else 0

    if daily_sum >= MAX_DAILY_POINTS:
        # Лимит исчерпан — только обновляем last_message_at
        await conn.execute(
            "UPDATE relationships SET last_message_at = ? WHERE id = ?",
            (now, rel["id"]),
        )
        await conn.commit()
        return await get_relationship(user_from, user_to)

    # Начисляем очки
    points_to_add = 1  # база за сообщение

    # Проверяем активность обоих за 24 часа
    day_ago = now - 86400
    cur = await conn.execute(
        """SELECT COUNT(DISTINCT user_from) AS cnt
           FROM relationship_events
           WHERE pair_u1 = ? AND pair_u2 = ? AND event_at > ?""",
        (u1, u2, day_ago),
    )
    row = await cur.fetchone()
    if row and row["cnt"] >= 2:
        points_to_add += STREAK_BONUS_24H

    # Проверяем streak (2 дня подряд)
    yesterday = today - 86400
    cur = await conn.execute(
        """SELECT 1 FROM relationship_events
           WHERE pair_u1 = ? AND pair_u2 = ? AND day_start = ? LIMIT 1""",
        (u1, u2, yesterday),
    )
    has_yesterday = await cur.fetchone()
    if has_yesterday:
        points_to_add += STREAK_BONUS_2DAYS

    # Проверяем streak (5 дней подряд)
    five_days_ago = today - 4 * 86400
    cur = await conn.execute(
        """SELECT COUNT(DISTINCT day_start) AS cnt
           FROM relationship_events
           WHERE pair_u1 = ? AND pair_u2 = ? AND day_start >= ?""",
        (u1, u2, five_days_ago),
    )
    row = await cur.fetchone()
    if row and row["cnt"] >= 5:
        points_to_add += STREAK_BONUS_5DAYS

    # Штрафы за тишину отключены: прежняя логика наказывала пару именно в момент
    # возвращения к общению (и обнуляла самое первое сообщение). Оставляем только
    # положительное начисление — очки растут, но не уходят в минус.

    # Записываем событие
    await conn.execute(
        """INSERT INTO relationship_events
           (pair_u1, pair_u2, user_from, event_at, day_start, delta)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (u1, u2, user_from, now, today, points_to_add),
    )

    # Обновляем points и last_message_at
    new_points = max(0, rel["points"] + points_to_add)
    await conn.execute(
        "UPDATE relationships SET points = ?, last_message_at = ? WHERE id = ?",
        (new_points, now, rel["id"]),
    )
    await conn.commit()

    # Пересчитываем уровень
    await _recalc_level(rel["id"], new_points)

    return await get_relationship(user_from, user_to)


async def _recalc_level(rel_id: int, points: int) -> None:
    """Обновляет level на основе points."""
    new_level = 0
    for lvl, _, threshold in LEVELS:
        if points >= threshold:
            new_level = lvl + 1
        else:
            break
    new_level = min(new_level, len(LEVELS) - 1)

    conn = await db.get_db()
    await conn.execute(
        "UPDATE relationships SET level = ? WHERE id = ?",
        (new_level, rel_id),
    )
    await conn.commit()


def format_status(rel: dict, for_user_id: int) -> str:
    """Красивый текст статуса отношений."""
    if not rel:
        return "💔 Отношения не найдены."

    level = rel["level"]
    points = rel["points"]
    name, next_threshold = _level_info(level)

    if level >= len(LEVELS) - 1:
        bar = "█" * 10
        return f"{name}\n{points} очков\n{bar} Максимальный уровень!"

    progress = min(points, next_threshold)
    filled = int((progress / next_threshold) * 10)
    bar = "█" * filled + "░" * (10 - filled)

    return f"{name} ({points}/{next_threshold})\n{bar}\n\n💬 Общайтесь чаще, чтобы расти вместе!"
