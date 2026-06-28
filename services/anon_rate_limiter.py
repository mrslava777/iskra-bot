"""Rate limiting для анонимного чата — чистая логика, без БД."""
import asyncio
import time
from collections import deque
from typing import Deque

from config import ANON_RATE_LIMIT_MSG_PER_MIN
from data.constants import AnonChat

_anon_msg_timestamps: dict[int, Deque[float]] = {}
_cleanup_lock = asyncio.Lock()
_last_cleanup = 0.0


async def _cleanup_old_entries() -> None:
    """Периодически очищает старые записи из словаря."""
    global _last_cleanup
    now = time.time()

    # Очищаем не чаще раза в 5 минут
    if now - _last_cleanup < 300:
        return

    async with _cleanup_lock:
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
    now = time.time()

    # Запускаем очистку в фоне (не блокируем)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_cleanup_old_entries())
    except RuntimeError:
        pass

    timestamps = _anon_msg_timestamps.get(tg_id)
    if timestamps is None:
        timestamps = deque(maxlen=ANON_RATE_LIMIT_MSG_PER_MIN)
        _anon_msg_timestamps[tg_id] = timestamps

    while timestamps and now - timestamps[0] >= AnonChat.RATE_LIMIT_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= ANON_RATE_LIMIT_MSG_PER_MIN:
        wait = int(AnonChat.RATE_LIMIT_WINDOW - (now - timestamps[0]))
        return False, max(1, wait)

    timestamps.append(now)
    return True, 0
