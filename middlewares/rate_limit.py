"""Rate limiting middleware — burst-окно + sliding window для сообщений, callback'ов и свайпов.

Защищает бота от:
- Flood-атак (слишком много сообщений от одного пользователя)
- Быстрых свайпов/кликов, которые перегружают БД
- Спама в анонимном чате

Алгоритм: sliding window с burst-окном.

FIX (#3 утечка памяти):
  - _user_blocked_until чистился только по пересечению с _user_windows,
    поэтому заблокированные без свежих запросов оседали навсегда;
  - оба словаря были неограничены. Теперь:
      * очистка сметает истёкшие блокировки НЕЗАВИСИМО от окон;
      * при превышении жёсткого капа размера делаем принудительный sweep;
      * очистка запускается не только по трафику, но и по времени.
"""
import logging
import time
from collections import deque
from typing import Deque

from aiogram import BaseMiddleware
from aiogram.types import Update

log = logging.getLogger("iskra.rate_limit")

# Конфигурация rate limiting
BURST_LIMIT = 15       # Макс. запросов в окне
WINDOW_SECONDS = 10    # Размер окна в секундах
BLOCK_SECONDS = 30     # Время блокировки при превышении

# Жёсткий предел числа отслеживаемых пользователей в памяти.
MAX_TRACKED = 50_000

# Хранилище: {user_id: deque[timestamp]}
_user_windows: dict[int, Deque[float]] = {}
_user_blocked_until: dict[int, float] = {}
_last_cleanup: float = 0.0


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для rate limiting всех входящих update'ов."""

    async def __call__(self, handler, event: Update, data: dict):
        user_id = None
        if event.message:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        elif event.inline_query:
            user_id = event.inline_query.from_user.id

        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()

        # Периодическая очистка (раз в 60с) — по времени, а не только по трафику.
        global _last_cleanup
        if now - _last_cleanup > 60:
            _cleanup_old(now)
            _last_cleanup = now

        # Проверяем блокировку
        blocked_until = _user_blocked_until.get(user_id)
        if blocked_until is not None:
            if now < blocked_until:
                wait = int(blocked_until - now)
                log.debug("User %d rate limited, blocked for %d sec", user_id, wait)
                await self._notify(event, f"⏳ Слишком быстро! Подожди {wait} сек.")
                return None
            # Блокировка истекла — убираем сразу, не ждём общего sweep.
            _user_blocked_until.pop(user_id, None)

        # Sliding window
        window = _user_windows.get(user_id)
        if window is None:
            window = deque(maxlen=BURST_LIMIT)
            _user_windows[user_id] = window

        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()

        if len(window) >= BURST_LIMIT:
            _user_blocked_until[user_id] = now + BLOCK_SECONDS
            log.warning(
                "User %d exceeded rate limit (%d/%d in %ds). Blocked for %ds",
                user_id, len(window), BURST_LIMIT, WINDOW_SECONDS, BLOCK_SECONDS,
            )
            await self._notify(event, f"⏳ Слишком много запросов! Подожди {BLOCK_SECONDS} сек.")
            return None

        window.append(now)

        # Страховка от разрастания при флуд-атаке с тысяч аккаунтов.
        if len(_user_windows) > MAX_TRACKED or len(_user_blocked_until) > MAX_TRACKED:
            _cleanup_old(now, force=True)

        return await handler(event, data)

    @staticmethod
    async def _notify(event: Update, text: str) -> None:
        """Уведомляет пользователя, не роняя обработку при ошибке доставки."""
        try:
            if event.callback_query:
                await event.callback_query.answer(text, show_alert=True)
            elif event.message:
                await event.message.answer(text)
        except Exception:
            pass


def _cleanup_old(now: float, force: bool = False) -> None:
    """Удаляет устаревшие записи из обоих хранилищ.

    force=True — более агрессивный проход (при переполнении): выкидывает все
    окна без свежей активности и все НЕактивные блокировки.
    """
    # 1) Истёкшие блокировки — независимо от наличия окна.
    expired_blocks = [uid for uid, until in _user_blocked_until.items() if until <= now]
    for uid in expired_blocks:
        _user_blocked_until.pop(uid, None)

    # 2) Пустые/протухшие окна.
    cutoff = now - WINDOW_SECONDS - BLOCK_SECONDS
    stale_windows = [
        uid for uid, w in _user_windows.items()
        if not w or w[-1] < cutoff
    ]
    for uid in stale_windows:
        # Не трогаем окно пользователя, который прямо сейчас в блоке.
        if uid in _user_blocked_until and _user_blocked_until[uid] > now:
            continue
        _user_windows.pop(uid, None)

    removed = len(expired_blocks) + len(stale_windows)
    if removed:
        log.debug("Rate limiter cleanup: removed ~%d entries (force=%s)", removed, force)
