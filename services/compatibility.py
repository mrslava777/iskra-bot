"""Расчёт совместимости по интересам — чистая функция, без зависимостей от БД.

FIX: compat_bar() приведён к единому алгоритму с _mini_bar().
FIX v5: увеличен CACHE_TTL с 300 до 600 сек — совместимость редко меняется,
        а запросов много.
"""
import time
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


def _compute_compat(a_raw: str | None, b_raw: str | None) -> int:
    """Чистый расчёт совместимости без кэширования."""
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    if not a or not b:
        return Compatibility.BASE
    inter = len(a & b)
    union = len(a | b)
    base = inter / union if union else 0
    pct = int(round(Compatibility.OFFSET + base * Compatibility.MULTIPLIER))
    if inter >= Compatibility.BONUS_THRESHOLD:
        pct = min(Compatibility.MAX, pct + Compatibility.BONUS)
    return max(Compatibility.MIN, min(Compatibility.MAX, pct))


def compatibility(a_raw: str | None, b_raw: str | None) -> int:
    """Процент совместимости по общим интересам (Жаккар + бонус).

    Кэширование: in-memory TTL-cache с ограничением размера.
    Безопасность: кэш используется только из главного потока event-loop,
    OrderedDict не требует lock для синхронных операций в asyncio.

    FIX v5: TTL увеличен до 600 сек — интересы меняются редко, а совместимость
    вычисляется при каждом показе анкеты. Экономит CPU и ускоряет ответ.
    """
    now = time.monotonic()
    cache_key = (a_raw, b_raw)

    cached = _compat_cache.get(cache_key)
    if cached is not None:
        cached_val, cached_at = cached
        # FIX v5: TTL 600 сек вместо 300
        if now - cached_at < 600.0:
            _compat_cache.move_to_end(cache_key)
            return cached_val
        del _compat_cache[cache_key]

    result = _compute_compat(a_raw, b_raw)

    _compat_cache[cache_key] = (result, now)
    if len(_compat_cache) > Compatibility.MAX_CACHE_SIZE:
        _compat_cache.popitem(last=False)
    return result


def common_interests(a_raw: str | None, b_raw: str | None) -> list[str]:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    return [INTERESTS[i] for i in sorted(a & b)]


def compat_bar(pct: int) -> str:
    """Прогресс-бар совместимости.

    FIX: приведён к единому алгоритму с _mini_bar() в badges.py.
    round() мог давать 11 при pct > 105 (невозможно, но опасно);
    min() + целочисленное деление безопаснее и единообразнее.
    """
    filled = min(ProgressBar.SIZE, pct * ProgressBar.SIZE // 100)
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
