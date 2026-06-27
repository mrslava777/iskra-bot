"""Форматирование карточек анкет — презентация.

format_profile        — синхронная версия (без значков/совместимости),
                        для финала регистрации.
format_profile_async  — асинхронная версия со значками и совместимостью.
"""
from data.content import daily_question
from services.compatibility import (
    common_interests,
    compat_bar,
    compatibility,
    fire_level,
    gender_emoji,
    interests_text,
)


def format_profile(user: dict) -> str:
    """Текст-карточка анкеты (без значков и совместимости)."""
    return _base_lines(user)


def _base_lines(user: dict) -> str:
    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "—"
    verified = " ✅" if user["verified"] else ""
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  •  📍 {city}"]

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n🏷 {interests}")

    if user["daily_a"]:
        q = daily_question(user["daily_q"] or 0)
        lines.append(f"\n💭 <i>{q}</i>\n— {user['daily_a']}")

    if user["bio"]:
        lines.append(f"\n📝 {user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")
    return "\n".join(lines)


async def format_profile_async(
    user: dict,
    viewer: dict | None = None,
    show_compat: bool = False,
    show_badges: bool = False,
) -> str:
    """Карточка анкеты со значками и (опционально) совместимостью."""
    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "—"
    verified = " ✅" if user["verified"] else ""
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  •  📍 {city}"]

    if show_badges:
        from services.badge_service import get_user_badges
        from services.badge_formatter import format_user_badges_inline
        badges = await get_user_badges(user["tg_id"])
        badge_line = format_user_badges_inline(badges)
        if badge_line:
            lines.append(badge_line)

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n🏷 {interests}")

    if user["daily_a"]:
        q = daily_question(user["daily_q"] or 0)
        lines.append(f"\n💭 <i>{q}</i>\n— {user['daily_a']}")

    if user["bio"]:
        lines.append(f"\n📝 {user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")

    if show_compat and viewer is not None:
        pct = compatibility(viewer["interests"], user["interests"])
        common = common_interests(viewer["interests"], user["interests"])
        bar = compat_bar(pct)
        lines.append(f"\n💞 Совместимость: <b>{pct}%</b>\n{bar}")
        if common:
            lines.append("🏷 Общее: " + ", ".join(common))

    return "\n".join(lines)
