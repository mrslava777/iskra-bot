"""Расчёт совместимости и оформление анкет."""
from typing import Iterable

from data.content import INTERESTS


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
        return "—"
    return " ".join(INTERESTS[i] for i in idx)


def compatibility(a_raw: str | None, b_raw: str | None) -> int:
    """Процент совместимости по общим интересам (Жаккар + бонус)."""
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    if not a or not b:
        return 50  # нейтрально, если интересы не заполнены
    inter = len(a & b)
    union = len(a | b)
    base = inter / union if union else 0
    # Немного «подсластим» шкалу, чтобы цифры были живее
    pct = int(round(40 + base * 60))
    if inter >= 3:
        pct = min(99, pct + 5)
    return max(35, min(99, pct))


def common_interests(a_raw: str | None, b_raw: str | None) -> list[str]:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    return [INTERESTS[i] for i in sorted(a & b)]


def gender_emoji(g: str | None) -> str:
    return {"m": "👨", "f": "👩"}.get(g or "", "🧑")


def fire_level(rating: int) -> str:
    """Огоньки рейтинга анкеты."""
    if rating >= 50:
        return "🔥🔥🔥"
    if rating >= 20:
        return "🔥🔥"
    if rating >= 5:
        return "🔥"
    return "✨"


def profile_caption(user, *, viewer=None, show_compat: bool = False) -> str:
    """Текст-карточка анкеты. viewer — кто смотрит (для совместимости)."""
    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "—"
    lines = [f"<b>{name}</b>, {age} {gender_emoji(user['gender'])}  •  📍 {city}"]

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n🏷 {interests}")

    if user["daily_a"]:
        from data.content import daily_question

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
        extra = f"  ({', '.join(common)})" if common else ""
        lines.append(f"\n💞 Совместимость: <b>{pct}%</b> {bar}{extra}")

    return "\n".join(lines)


def compat_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "🟩" * filled + "⬜" * (10 - filled)
