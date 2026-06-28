"""Redis-based sliding window rate limiter for anon chat.

Uses a Lua script for atomicity: maintain a sorted set per user with timestamps
and trim entries outside the window. Returns (allowed: bool, wait_seconds: int).

Requires REDIS_URL in config.
"""
import time
import logging
from typing import Tuple

import redis.asyncio as aioredis

from config import REDIS_URL, ANON_RATE_LIMIT_MSG_PER_MIN

log = logging.getLogger("iskra.redis_rate_limiter")

redis_client = None
if REDIS_URL:
    try:
        redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    except Exception as e:
        log.warning("Не удалось подключиться к Redis: %s", e)

LUA_SLIDING = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local cnt = redis.call('ZCARD', key)
if cnt >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2]
  return {0, oldest + window - now}
else
  redis.call('ZADD', key, now, now)
  redis.call('EXPIRE', key, window + 2)
  return {1, 0}
end
"""


async def check_rate_limit(tg_id: int) -> Tuple[bool, int]:
    if redis_client is None:
        # Fallback: allow everything (or could implement local limiter)
        return True, 0

    now = int(time.time())
    key = f"anon:msgs:{tg_id}"
    try:
        res = await redis_client.eval(LUA_SLIDING, 1, key, now, 60, ANON_RATE_LIMIT_MSG_PER_MIN)
        # Redis returns list of strings, convert
        allowed = bool(int(res[0]))
        wait = int(res[1])
        return allowed, wait
    except Exception as e:
        log.warning("Redis rate limiter error: %s", e)
        return True, 0
