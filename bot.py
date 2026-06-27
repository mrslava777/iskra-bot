"""Точка входа бота.

Режимы работы выбираются переменными окружения и по умолчанию полностью
повторяют текущее поведение (long polling + in-memory FSM):

  • FSM-хранилище: Redis, если задан ``REDIS_URL`` (иначе in-memory).
  • Транспорт: webhook, если задан ``WEBHOOK_URL`` (иначе long polling).

Это позволяет масштабироваться (несколько инстансов за webhook + общий Redis)
без изменения кода — достаточно выставить переменные окружения.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

import database as db
from config import BOT_TOKEN
from handlers import setup_routers
from health import start_health_server
from middlewares import ThrottlingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
log = logging.getLogger("iskra")


def _make_storage():
    """Redis-хранилище FSM, если задан REDIS_URL, иначе in-memory."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        log.info("FSM-хранилище: Redis")
        return RedisStorage.from_url(redis_url)
    log.info("FSM-хранилище: in-memory (для масштабирования задай REDIS_URL)")
    return MemoryStorage()


def _build_dispatcher(bot: Bot) -> Dispatcher:
    dp = Dispatcher(storage=_make_storage())

    # Анти-флуд на входящие сообщения.
    dp.message.middleware(ThrottlingMiddleware())

    root = setup_routers()

    @root.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка в апдейте: %s", event.exception)
        return True

    dp.include_router(root)

    async def _on_startup() -> None:
        await db.init_db()
        log.info("База инициализирована: %s", db.DB_PATH)

    dp.startup.register(_on_startup)

    async def _on_shutdown() -> None:
        log.info("Остановка: закрываю БД и сессию бота…")
        await db.close_db()
        await bot.session.close()

    dp.shutdown.register(_on_shutdown)
    return dp


async def _run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Запуск в режиме webhook (для горизонтального масштабирования)."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    base = os.getenv("WEBHOOK_URL", "").rstrip("/")
    path = os.getenv("WEBHOOK_PATH", "/webhook")
    secret = os.getenv("WEBHOOK_SECRET", "").strip() or None
    port = int(os.getenv("PORT", "8080"))

    app = web.Application()
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=path)
    setup_application(app, dp, bot=bot)

    await bot.set_webhook(base + path, secret_token=secret, drop_pending_updates=True)
    log.info("Режим webhook: %s (порт %s)", base + path, port)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    await asyncio.Event().wait()  # держим процесс живым


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    """Запуск в режиме long polling (по умолчанию)."""
    async def _start_health() -> None:
        await start_health_server()

    dp.startup.register(_start_health)
    log.info("Режим long polling")
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан! Установи переменную окружения.")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = _build_dispatcher(bot)

    use_webhook = bool(os.getenv("WEBHOOK_URL", "").strip())
    try:
        if use_webhook:
            asyncio.run(_run_webhook(bot, dp))
        else:
            asyncio.run(_run_polling(bot, dp))
    except KeyboardInterrupt:
        log.info("Остановка по Ctrl+C…")


if __name__ == "__main__":
    main()
