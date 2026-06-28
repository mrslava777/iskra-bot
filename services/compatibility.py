"""Расчёт совместимости по интересам — чистая функция, без зависимостей от БД."""
from collections import OrderedDict

from data.content import INTERESTS
from data.constants import Compatibility, ProgressBar, FireRating, EMOJI
from data.enums import Gender

_compat_cache: OrderedDict[tuple[str | None, str | None], tuple[int, float]] = OrderedDict()


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
    import time
    now = time.time()
    cache_key = (a_raw, b_raw)

    if cache_key in _compat_cache:
        cached_val, cached_at = _compat_cache[cache_key]
        if now - cached_at < Compatibility.CACHE_TTL:
            _compat_cache.move_to_end(cache_key)
            return cached_val
        del _compat_cache[cache_key]

    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    if not a or not b:
        result = Compatibility.BASE
    else:
        inter = len(a & b)
        union = len(a | b)
        base = inter / union if union else 0
        pct = int(round(Compatibility.OFFSET + base * Compatibility.MULTIPLIER))
        if inter >= Compatibility.BONUS_THRESHOLD:
            pct = min(Compatibility.MAX, pct + Compatibility.BONUS)
        result = max(Compatibility.MIN, min(Compatibility.MAX, pct))

    _compat_cache[cache_key] = (result, now)
    if len(_compat_cache) > Compatibility.MAX_CACHE_SIZE:
        _compat_cache.popitem(last=False)
    return result


def common_interests(a_raw: str | None, b_raw: str | None) -> list[str]:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    return [INTERESTS[i] for i in sorted(a & b)]


def compat_bar(pct: int) -> str:
    filled = round(pct / ProgressBar.SIZE)
    return ProgressBar.FILLED * filled + ProgressBar.EMPTY * (ProgressBar.SIZE - filled)


def gender_emoji(g: str | None) -> str:
    return {
        Gender.MALE.value: EMOJI.MALE,
        Gender.FEMALE.value: EMOJI.FEMALE,
    }.get(g or "", EMOJI.UNKNOWN_GENDER)


def fire_level(rating: int) -> str:
    if rating >= FireRating.HIGH:
        return EMOJI.FIRE_MAX
    if rating >= FireRating.MID:
        return EMOJI.FIRE_HIGH
    if rating >= FireRating.LOW:
        return EMOJI.FIRE_MID
    return EMOJI.FIRE_LOW
