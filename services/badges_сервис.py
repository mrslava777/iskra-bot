"""Сервис работы со значками (Артефактами)."""
import time
from typing import Optional

import aiosqlite

from .. import database as db
from ..data.badges import BADGE_BY_ID, BADGES, RARITY_EMOJI, RARITY_ORDER, rarity_label


async def _get_stats(user_id: int) -> dict:
    """Собирает статистику пользователя для проверки условий значков."""
    conn = await db.get_db()
    stats: dict = {}

    # Количество мэтчей
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM matches WHERE a_id = ? OR b_id = ?",
        (user_id, user_id),
    )
    row = await cur.fetchone()
    stats["matches"] = row["c"] if row else 0

    # Отправленные лайки
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM likes WHERE from_id = ? AND is_like = 1",
        (user_id,),
    )
    row = await cur.fetchone()
    stats["likes_sent"] = row["c"] if row else 0

    # Лайки с сообщением (msglike)
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM likes WHERE from_id = ? AND is_like = 1 AND message IS NOT NULL",
        (user_id,),
    )
    row = await cur.fetchone()
    stats["msglikes"] = row["c"] if row else 0

    # Отправленные жалобы
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM reports WHERE from_id = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    stats["reports_sent"] = row["c"] if row else 0

    # Фото в галерее
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM user_photos WHERE tg_id = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    stats["photo_count"] = row["c"] if row else 0

    # Анонимные открытия
    cur = await conn.execute(
        "SELECT COUNT(*) c FROM anon_sessions WHERE (a_id = ? AND a_reveal = 1) OR (b_id = ? AND b_reveal = 1)",
        (user_id, user_id),
    )
    row = await cur.fetchone()
    stats["anon_reveals"] = row["c"] if row else 0

    # Сообщения в анонимном чате
    cur = await conn.execute(
        "SELECT anon_messages_count FROM users WHERE tg_id = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    stats["anon_messages"] = row["anon_messages_count"] if row and row["anon_messages_count"] else 0

    # Максимальная совместимость (из лайкнутых)
    cur = await conn.execute(
        """\n        SELECT u.interests FROM likes l\n        JOIN users u ON u.tg_id = l.to_id\n        WHERE l.from_id = ? AND l.is_like = 1\n        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    from .matching import compatibility
    me = await db.get_user(user_id)
    max_compat = 0
    if me:
        for r in rows:
            pct = compatibility(me["interests"], r["interests"])
            if pct > max_compat:
                max_compat = pct
    stats["max_compat"] = max_compat

    return stats


async def check_and_award(user_id: int) -> list[dict]:
    """Проверяет все значки и выдаёт новые. Возвращает список НОВЫХ значков."""
    user = await db.get_user(user_id)
    if not user:
        return []

    # Получаем уже имеющиеся значки
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT badge_id FROM user_badges WHERE tg_id = ?",
        (user_id,),
    )
    existing_ids = {row["badge_id"] async for row in cur}

    stats = await _get_stats(user_id)
    new_badges: list[dict] = []

    for badge in BADGES:
        if badge["id"] in existing_ids:
            continue
        if badge["condition"](user, stats):
            # Выдаём значок!
            now = int(time.time())
            await conn.execute(
                "INSERT INTO user_badges (tg_id, badge_id, awarded_at) VALUES (?, ?, ?)",
                (user_id, badge["id"], now),
            )
            new_badges.append(badge)

    if new_badges:
        await conn.commit()
    return new_badges


async def get_user_badges(user_id: int) -> list[dict]:
    """Возвращает список значков пользователя с метаданными."""
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT badge_id, awarded_at FROM user_badges WHERE tg_id = ? ORDER BY awarded_at DESC",
        (user_id,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        badge = BADGE_BY_ID.get(r["badge_id"])
        if badge:
            result.append({
                **badge,
                "awarded_at": r["awarded_at"],
            })
    # Сортируем по редкости
    result.sort(key=lambda x: (-RARITY_ORDER[x["rarity"]], -x["awarded_at"]))
    return result


async def has_badge(user_id: int, badge_id: str) -> bool:
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT 1 FROM user_badges WHERE tg_id = ? AND badge_id = ?",
        (user_id, badge_id),
    )
    return await cur.fetchone() is not None


async def get_badge_progress(user_id: int) -> dict:
    """Возвращает прогресс по каждому ещё не полученному значку."""
    user = await db.get_user(user_id)
    if not user:
        return {}
    stats = await _get_stats(user_id)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT badge_id FROM user_badges WHERE tg_id = ?",
        (user_id,),
    )
    existing = {row["badge_id"] async for row in cur}

    progress = {}
    for badge in BADGES:
        if badge["id"] in existing:
            continue
        progress[badge["id"]] = {
            "badge": badge,
            "progress": _calc_progress(badge["id"], stats),
        }
    return progress


def _calc_progress(badge_id: str, stats: dict) -> str:
    """Возвращает текст прогресса для значка."""
    mapping = {
        "first_like": f"{stats.get('likes_sent', 0)}/1 лайк",
        "first_match": f"{stats.get('matches', 0)}/1 мэтч",
        "ten_matches": f"{stats.get('matches', 0)}/10 мэтчей",
        "fifty_matches": f"{stats.get('matches', 0)}/50 мэтчей",
        "hundred_likes": f"{stats.get('likes_sent', 0)}/100 лайков",
        "streak_7": f"{stats.get('streak', 0)}/7 дней",
        "streak_30": f"{stats.get('streak', 0)}/30 дней",
        "popular": f"{stats.get('rating', 0)}/50 симпатий",
        "high_compat": f"{stats.get('max_compat', 0)}/95% совместимости",
        "revealer": f"{stats.get('anon_reveals', 0)}/10 открытий",
        "chatter": f"{stats.get('anon_messages', 0)}/100 сообщений",
        "photographer": f"{stats.get('photo_count', 0)}/5 фото",
        "icebreaker": f"{stats.get('msglikes', 0)}/5 лайков с сообщением",
        "reporter": f"{stats.get('reports_sent', 0)}/1 жалоба",
    }
    return mapping.get(badge_id, "В процессе...")


def format_badges_list(badges: list[dict]) -> str:
    """Красивое форматирование списка значков."""
    if not badges:
        return "У тебя пока нет значков. Будь активнее! 🔥"
    lines = ["🏆 <b>Твои Артефакты</b>\n"]
    current_rarity = None
    for b in badges:
        if b["rarity"] != current_rarity:
            current_rarity = b["rarity"]
            emoji = RARITY_EMOJI.get(current_rarity, "⚪")
            label = rarity_label(current_rarity)
            lines.append(f"\n{emoji} <b>{label}</b>")
        lines.append(f"  {b['icon']} <b>{b['name']}</b> — {b['description']}")
    return "\n".join(lines)


def format_badge_card(badge: dict, is_new: bool = False) -> str:
    """Красивое оформление одного значка."""
    rarity_emoji = RARITY_EMOJI.get(badge["rarity"], "⚪")
    label = rarity_label(badge["rarity"])
    new_text = "\n\n🎉 <b>НОВЫЙ АРТЕФАКТ!</b>" if is_new else ""
    return (
        f"{badge['icon']} <b>{badge['name']}</b>{new_text}\n\n"
        f"{rarity_emoji} Редкость: <b>{label}</b>\n"
        f"📝 {badge['description']}"
    )


# ===== НОВЫЕ ФУНКЦИИ ДЛЯ ИНТЕГРАЦИИ В АНКЕТЫ =====

def format_user_badges_inline(badges: list[dict], max_show: int = 5) -> str:
    """Форматирует значки для показа в анкете (одной строкой с иконками).\n\n    Показывает до max_show значков, приоритет — по редкости.\n    """
    if not badges:
        return ""

    # Берём топ по редкости
    sorted_badges = sorted(badges, key=lambda x: -RARITY_ORDER[x["rarity"]])
    shown = sorted_badges[:max_show]

    icons = " ".join(b["icon"] for b in shown)
    total = len(badges)

    if total > max_show:
        return f"\n🏆 {icons} +{total - max_show}"
    return f"\n🏆 {icons}"


def format_user_badges_detailed(badges: list[dict]) -> str:
    """Подробное форматирование значков для анкеты (с названиями)."""
    if not badges:
        return ""

    lines = ["\n🏆 <b>Артефакты:</b>"]
    current_rarity = None

    for b in badges[:8]:  # Показываем максимум 8
        if b["rarity"] != current_rarity:
            current_rarity = b["rarity"]
            emoji = RARITY_EMOJI.get(current_rarity, "⚪")
            label = rarity_label(current_rarity)
            lines.append(f"  {emoji} <i>{label}</i>")
        lines.append(f"    {b['icon']} {b['name']}")

    if len(badges) > 8:
        lines.append(f"    ...и ещё {len(badges) - 8}")

    return "\n".join(lines)
