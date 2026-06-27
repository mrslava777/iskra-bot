"""Rate limiting для анонимного чата — чистая логика, без БД."""
import time
from collections import deque
from typing import Deque

from config import ANON_RATE_LIMIT_MSG_PER_MIN
from data.constants import AnonChat

_anon_msg_timestamps: dict[int, Deque[float]] = {}


def check_rate_limit(tg_id: int) -> tuple[bool, int]:
    """Проверяет rate limit. Возвращает (allowed, seconds_to_wait)."""
    now = time.time()
    global _anon_msg_timestamps

    if len(_anon_msg_timestamps) > AnonChat.MAX_TRACKED_USERS:
        cutoff = now - AnonChat.CLEANUP_CUTOFF
        _anon_msg_timestamps = {
            uid: ts for uid, ts in _anon_msg_timestamps.items()
            if ts and ts[-1] > cutoff
        }

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
