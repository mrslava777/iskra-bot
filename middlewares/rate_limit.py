"""Rate limiting middleware — burst-окно + sliding window для сообщений, callback'ов и свайпов.

Защищает бота от:
- Flood-атак (слишком много сообщений от одного пользователя)
- Быстрых свайпов/кликов, которые перегружают БД
- Спама в анонимном чате

Алгоритм: sliding window с burst-окном.
- Каждый пользователь имеет счётчик запросов в окне
- Окно сдвигается: старые запросы вытесняются
- При превышении лимита — отклоняем с указанием времени ожидания
"""
import asyncio
import logging
import time
from collections import deque
from typing import Deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, Update

log = logging.getLogger("iskra.rate_limit")

# Конфигурация rate limiting
BURST_LIMIT = 15       # Макс. запросов в окне
WINDOW_SECONDS = 10    # Размер окна в секундах
BLOCK_SECONDS = 30     # Время блокировки при превышении

# Хранилище: {user_id: deque[timestamp]}
_user_windows: dict[int, Deque[float]] = {}
_user_blocked_until: dict[int, float] = {}
_last_cleanup: float = 0.0


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для rate limiting всех входящих update'ов."""

    async def __call__(self, handler, event: Update, data: dict):
        # Определяем user_id из любого типа update
        user_id = None
        if event.message:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        elif event.inline_query:
            user_id = event.inline_query.from_user.id

        if user_id is None:
            # Системные update'ы без пользователя — пропускаем
            return await handler(event, data)

        # Проверяем блокировку
        now = time.monotonic()
        blocked_until = _user_blocked_until.get(user_id)
        if blocked_until and now < blocked_until:
            wait = int(blocked_until - now)
            log.debug("User %d rate limited, blocked for %d sec", user_id, wait)
            # Отвечаем на callback если это callback
            if event.callback_query:
                try:
                    await event.callback_query.answer(
                        f"⏳ Слишком быстро! Подожди {wait} сек.",
                        show_alert=True,
                    )
                except Exception:
                    pass
            elif event.message:
                try:
                    await event.message.answer(
                        f"⏳ Слишком быстро! Подожди {wait} сек."
                    )
                except Exception:
                    pass
            return None  # Не пропускаем хендлер

        # Sliding window
        window = _user_windows.get(user_id)
        if window is None:
            window = deque(maxlen=BURST_LIMIT)
            _user_windows[user_id] = window

        # Убираем устаревшие записи
        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()

        # Проверяем лимит
        if len(window) >= BURST_LIMIT:
            # Блокируем пользователя
            _user_blocked_until[user_id] = now + BLOCK_SECONDS
            log.warning(
                "User %d exceeded rate limit (%d/%d in %ds). Blocked for %ds",
                user_id, len(window), BURST_LIMIT, WINDOW_SECONDS, BLOCK_SECONDS
            )
            if event.callback_query:
                try:
                    await event.callback_query.answer(
                        f"⏳ Слишком много запросов! Подожди {BLOCK_SECONDS} сек.",
                        show_alert=True,
                    )
                except Exception:
                    pass
            elif event.message:
                try:
                    await event.message.answer(
                        f"⏳ Слишком много запросов! Подожди {BLOCK_SECONDS} сек."
                    )
                except Exception:
                    pass
            return None

        # Регистрируем запрос
        window.append(now)

        # Периодическая очистка (раз в 5 минут)
        global _last_cleanup
        if now - _last_cleanup > 300:
            _cleanup_old(now)
            _last_cleanup = now

        return await handler(event, data)


def _cleanup_old(now: float) -> None:
    """Удаляет старые записи из хранилища."""
    cutoff = now - WINDOW_SECONDS - BLOCK_SECONDS
    to_remove = [
        uid for uid, window in _user_windows.items()
        if not window or window[-1] < cutoff
    ]
    for uid in to_remove:
        _user_windows.pop(uid, None)
        _user_blocked_until.pop(uid, None)
    if to_remove:
        log.debug("Cleaned up %d old rate limit entries", len(to_remove))
