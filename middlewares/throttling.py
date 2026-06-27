"""Анти-флуд middleware.

Лёгкая защита от спама/перегрузки: ограничивает частоту *входящих сообщений*
от одного пользователя. На inline-кнопки (callback) не влияет, чтобы не ломать
быстрый выбор интересов/настроек.

Хранилище — в памяти процесса (без внешних зависимостей, работает бесплатно).
Для одного инстанса этого достаточно; при горизонтальном масштабировании
лимит станет per-instance — это приемлемо как грубая защита.
"""
import time

from aiogram import BaseMiddleware
from aiogram.types import Message

# Минимальный интервал между сообщениями одного пользователя (сек).
DEFAULT_RATE = 0.3
# Чистим устаревшие записи, чтобы словарь не рос бесконечно.
_CLEANUP_AFTER = 300.0
_CLEANUP_EVERY = 1000


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = DEFAULT_RATE) -> None:
        self.rate = rate_limit
        self._last: dict[int, float] = {}
        self._calls = 0

    async def __call__(self, handler, event: Message, data: dict):
        user = data.get("event_from_user")
        if user is not None:
            now = time.monotonic()
            last = self._last.get(user.id, 0.0)
            if now - last < self.rate:
                # Слишком часто — тихо игнорируем это сообщение.
                return None
            self._last[user.id] = now
            self._maybe_cleanup(now)
        return await handler(event, data)

    def _maybe_cleanup(self, now: float) -> None:
        self._calls += 1
        if self._calls % _CLEANUP_EVERY:
            return
        stale = [uid for uid, ts in self._last.items() if now - ts > _CLEANUP_AFTER]
        for uid in stale:
            self._last.pop(uid, None)
