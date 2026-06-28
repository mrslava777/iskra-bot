"""Главный файл бота Искра — Webhook mode для Railway."""
import asyncio
import logging
import os
import signal

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN
from database.connection import close_db_pool
from handlers import setup_routers
from health import start_health_server, stop_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("iskra.main")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", "8080"))

_shutdown_event = asyncio.Event()


async def on_startup(bot: Bot) -> None:
    """Устанавливаем webhook при старте."""
    if WEBHOOK_HOST:
        webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
        await bot.set_webhook(webhook_url)
        log.info("Webhook установлен: %s", webhook_url)
    else:
        log.warning("WEBHOOK_HOST не задан, webhook не установлен")


async def on_shutdown(bot: Bot) -> None:
    """Graceful shutdown: удаляем webhook, закрываем пулы."""
    log.info("Начинаю graceful shutdown...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook удалён")
    except Exception as e:
        log.error("Ошибка при удалении webhook: %s", e)

    try:
        await close_db_pool()
        log.info("Пул БД закрыт")
    except Exception as e:
        log.error("Ошибка при закрытии пула БД: %s", e)

    try:
        await stop_health_server()
    except Exception as e:
        log.error("Ошибка при остановке health-сервера: %s", e)

    _shutdown_event.set()
    log.info("Graceful shutdown завершён")


def _setup_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Настраивает обработчики сигналов для graceful shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown_event.set()))


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Регистрируем все роутеры
    root_router = setup_routers()
    dp.include_router(root_router)

    # Регистрируем startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Создаём aiohttp приложение
    app = web.Application()

    # Health endpoints для Railway
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _ready_handler)

    # Webhook endpoint для Telegram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Setup application
    setup_application(app, dp, bot=bot)

    # Настраиваем обработку сигналов
    _setup_signal_handlers(asyncio.get_running_loop())

    # Запускаем health-сервер отдельной задачей
    health_task = asyncio.create_task(start_health_server())

    # Запускаем aiohttp сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Server started on port %s", PORT)

    # Ждём сигнала завершения
    await _shutdown_event.wait()

    # Cleanup
    await runner.cleanup()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass

    log.info("Server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Прервано пользователем")
