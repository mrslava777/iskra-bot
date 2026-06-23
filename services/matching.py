"""Расчет совместимости и оформление анкет."""
import time
from typing import Iterable

from data.content import INTERESTS, night_nickname, night_question


def parse_interests(raw: str | None) -> list[int]:
    if not raw:
        return []
    out = []
    for x in raw.split(","):
        x = x.strip()
        if x.isdigit():
            i = int(x)
            if 0 <= i < len(INTERESTS):
                out.append(i)
    return out


def interests_text(raw: str | None) -> str:
    idx = parse_interests(raw)
    if not idx:
        return "-"
    return " ".join(INTERESTS[i] for i in idx)


def compatibility(a_raw: str | None, b_raw: str | None) -> int:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    if not a or not b:
        return 50
    inter = len(a & b)
    union = len(a | b)
    base = inter / union if union else 0
    pct = int(round(40 + base * 60))
    if inter >= 3:
        pct = min(99, pct + 5)
    return max(35, min(99, pct))


def common_interests(a_raw: str | None, b_raw: str | None) -> list[str]:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    return [INTERESTS[i] for i in sorted(a & b)]


def gender_emoji(g: str | None) -> str:
    return {"m": "M", "f": "F"}.get(g or "", "?")


def fire_level(rating: int) -> str:
    if rating >= 50:
        return "***"
    if rating >= 20:
        return "**"
    if rating >= 5:
        return "*"
    return "+"


def is_night_mode() -> bool:
    hour = time.localtime().tm_hour
    return 0 <= hour < 6


def profile_caption(user, *, viewer=None, show_compat: bool = False, night_mode: bool = False) -> str:
    if night_mode:
        return _night_profile_caption(user, viewer=viewer, show_compat=show_compat)
    return _day_profile_caption(user, viewer=viewer, show_compat=show_compat)


def _day_profile_caption(user, *, viewer=None, show_compat: bool = False) -> str:
    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "-"
    try:
        verified = " [V]" if user["verified"] else ""
    except (KeyError, IndexError):
        verified = ""
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  -  {city}"]

    interests = interests_text(user["interests"])
    if interests != "-":
        lines.append(f"\n{interests}")

    if user["daily_a"]:
        from data.content import daily_question
        q = daily_question(user["daily_q"] or 0)
        lines.append(f"\n<i>{q}</i>\n- {user['daily_a']}")

    if user["bio"]:
        lines.append(f"\n{user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")

    if show_compat and viewer is not None:
        pct = compatibility(viewer["interests"], user["interests"])
        common = common_interests(viewer["interests"], user["interests"])
        bar = compat_bar(pct)
        lines.append(f"\nСовместимость: <b>{pct}%</b>\n{bar}")
        if common:
            lines.append("Общее: " + ", ".join(common))

    return "\n".join(lines)


def _night_profile_caption(user, *, viewer=None, show_compat: bool = False) -> str:
    seed = user["tg_id"]
    nickname = night_nickname(seed)
    age = user["age"]
    city = user["city"] or "Где-то там"

    lines = [f"<b>{nickname}</b>, {age}  -  {city}"]

    interests = interests_text(user["interests"])
    if interests != "-":
        lines.append(f"\nИнтересы скрыты до рассвета")

    q = night_question(user.get("daily_q", 0))
    if user.get("daily_a"):
        lines.append(f"\n<i>{q}</i>\n- {user['daily_a']}")
    else:
        lines.append(f"\n<i>{q}</i>\n- <i>Тишина...</i>")

    if user.get("bio"):
        short_bio = user["bio"][:80] + "..." if len(user["bio"]) > 80 else user["bio"]
        lines.append(f"\n{short_bio}")

    fire = fire_level(user.get("rating", 0))
    lines.append(f"\n{fire}")

    if show_compat and viewer is not None:
        pct = compatibility(viewer.get("interests"), user.get("interests"))
        if pct >= 80:
            lines.append(f"\nСудьбоносная встреча: <b>{pct}%</b>")
        elif pct >= 60:
            lines.append(f"\nЗвезды сошлись: <b>{pct}%</b>")
        else:
            lines.append(f"\nТени пересеклись: <b>{pct}%</b>")

    return "\n".join(lines)


def compat_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "[" + "=" * filled + "-" * (10 - filled) + "]"
