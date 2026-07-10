"""Расчёт совместимости по интересам — чистая функция, без зависимостей от БД.

FIX: compat_bar() приведён к единому алгоритму с _mini_bar().
FIX v5: CACHE_TTL увеличен до 600 сек.
FIX (#6 инвалидация кэша): добавлены clear_compat_cache() и
 invalidate_compat_for(raw). Раньше при смене интересов старые пары висели
 в кэше до истечения TTL (до 10 мин) и показывали неверный процент.
 Теперь user_repo при обновлении interests точечно чистит затронутые записи.
"""
import time
from collections import OrderedDict
from typing import Optional

from data.content import INTERESTS
from data.constants import Compatibility, ProgressBar, FireRating, EMOJI
from data.enums import Gender

_compat_cache: OrderedDict[tuple[Optional[str], Optional[str]], tuple[int, float]] = OrderedDict()

_COMPAT_TTL = 600.0


def parse_interests(raw: Optional[str]) -> list[int]:
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


def interests_text(raw: Optional[str]) -> str:
    idx = parse_interests(raw)
    if not idx:
        return "—"
    return " ".join(INTERESTS[i] for i in idx)


def _compute_compat(a_raw: Optional[str], b_raw: Optional[str]) -> int:
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


def compatibility(a_raw: Optional[str], b_raw: Optional[str]) -> int:
    """Процент совместимости по общим интересам (Жаккар + бонус). TTL-кэш."""
    now = time.monotonic()
    cache_key = (a_raw, b_raw)

    cached = _compat_cache.get(cache_key)
    if cached is not None:
        cached_val, cached_at = cached
        if now - cached_at < _COMPAT_TTL:
            _compat_cache.move_to_end(cache_key)
            return cached_val
        del _compat_cache[cache_key]

    result = _compute_compat(a_raw, b_raw)

    _compat_cache[cache_key] = (result, now)
    if len(_compat_cache) > Compatibility.MAX_CACHE_SIZE:
        _compat_cache.popitem(last=False)
    return result


def invalidate_compat_for(raw: Optional[str]) -> int:
    """Удаляет из кэша все пары, где участвует данная строка интересов.

    Вызывается при смене интересов пользователя. Возвращает число удалённых
    записей. Дёшево: ключи хранятся как (a_raw, b_raw).
    """
    keys = [k for k in _compat_cache if k[0] == raw or k[1] == raw]
    for k in keys:
        _compat_cache.pop(k, None)
    return len(keys)


def clear_compat_cache() -> None:
    """Полностью очищает кэш совместимости."""
    _compat_cache.clear()


def common_interests(a_raw: Optional[str], b_raw: Optional[str]) -> list[str]:
    a = set(parse_interests(a_raw))
    b = set(parse_interests(b_raw))
    return [INTERESTS[i] for i in sorted(a & b)]


def compat_bar(pct: int) -> str:
    """Прогресс-бар совместимости (единый алгоритм с _mini_bar())."""
    filled = min(ProgressBar.SIZE, pct * ProgressBar.SIZE // 100)
    return ProgressBar.FILLED * filled + ProgressBar.EMPTY * (ProgressBar.SIZE - filled)


def gender_emoji(g: Optional[str]) -> str:
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
