"""Форматирование карточек анкет — презентация.

format_profile        — синхронная версия (без значков/совместимости),
                        для финала регистрации.
format_profile_async  — асинхронная версия со значками и совместимостью.
FIX v5: принимает предзагруженные badges — убирает лишний запрос.
"""
from services.badge_formatter import format_user_badges_inline
from services.badge_service import get_user_badges
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
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  \u2022  \U0001f4cd {city}"]

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n\U0001f3f7 {interests}")

    if user["bio"]:
        lines.append(f"\n\U0001f4dd {user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")
    return "\n".join(lines)


async def format_profile_async(
    user: dict,
    viewer: dict | None = None,
    show_compat: bool = False,
    show_badges: bool = False,
    badges: list[dict] | None = None,  # FIX v5: предзагруженные значки
) -> str:
    """Карточка анкеты со значками и (опционально) совместимостью.

    FIX v5: если badges переданы — не делает запрос к БД.
    """
    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "—"
    verified = " ✅" if user["verified"] else ""
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  \u2022  \U0001f4cd {city}"]

    if show_badges:
        if badges is None:
            badges = await get_user_badges(user["tg_id"])
        badge_line = format_user_badges_inline(badges)
        if badge_line:
            lines.append(badge_line)

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n\U0001f3f7 {interests}")

    if user["bio"]:
        lines.append(f"\n\U0001f4dd {user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")

    if show_compat and viewer is not None:
        pct = compatibility(viewer["interests"], user["interests"])
        common = common_interests(viewer["interests"], user["interests"])
        bar = compat_bar(pct)
        lines.append(f"\n\U0001f49e Совместимость: <b>{pct}%</b>\n{bar}")
        if common:
            lines.append("\U0001f3f7 Общее: " + ", ".join(common))

    return "\n".join(lines)
