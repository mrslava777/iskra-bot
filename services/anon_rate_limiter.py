"""Rate limiting для анонимного чата — чистая логика, без БД.

FIX: убран fire-and-forget create_task (утечка ссылки, потерянные ошибки).
     Очистка вызывается синхронно и inline — она быстрая.
FIX: добавлен лимит MAX_TRACKED_USERS для защиты от безграничного роста словаря.
FIX: time.monotonic() вместо time.time() — не зависит от изменения системных часов.
"""
import time
from collections import deque
from typing import Deque

from config import ANON_RATE_LIMIT_MSG_PER_MIN
from data.constants import AnonChat

_anon_msg_timestamps: dict[int, Deque[float]] = {}
_last_cleanup: float = 0.0

# Защита от безграничного роста словаря
_MAX_TRACKED_USERS = 10_000


def _cleanup_old_entries() -> None:
    """Периодически очищает старые записи из словаря.

    FIX: сделана синхронной — не нужен asyncio.Lock для словаря,
    используемого только из одного потока event-loop.
    """
    global _last_cleanup
    now = time.monotonic()

    # Очищаем не чаще раза в 5 минут
    if now - _last_cleanup < 300:
        return

    cutoff = now - AnonChat.CLEANUP_CUTOFF
    to_remove = [
        uid for uid, ts in _anon_msg_timestamps.items()
        if not ts or ts[-1] < cutoff
    ]
    for uid in to_remove:
        del _anon_msg_timestamps[uid]

    _last_cleanup = now


def check_rate_limit(tg_id: int) -> tuple[bool, int]:
    """Проверяет rate limit. Возвращает (allowed, seconds_to_wait)."""
    now = time.monotonic()

    # Очистка старых записей (синхронно, быстро)
    _cleanup_old_entries()

    timestamps = _anon_msg_timestamps.get(tg_id)
    if timestamps is None:
        # Защита от переполнения: если слишком много пользователей,
        # вытесняем самого старого
        if len(_anon_msg_timestamps) >= _MAX_TRACKED_USERS:
            oldest_uid = next(iter(_anon_msg_timestamps))
            del _anon_msg_timestamps[oldest_uid]

        timestamps = deque(maxlen=ANON_RATE_LIMIT_MSG_PER_MIN)
        _anon_msg_timestamps[tg_id] = timestamps

    while timestamps and now - timestamps[0] >= AnonChat.RATE_LIMIT_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= ANON_RATE_LIMIT_MSG_PER_MIN:
        wait = int(AnonChat.RATE_LIMIT_WINDOW - (now - timestamps[0]))
        return False, max(1, wait)

    timestamps.append(now)
    return True, 0
