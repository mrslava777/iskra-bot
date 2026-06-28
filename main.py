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
from health import _health_handler, _ready_handler

logging.basicConfig(level=logging.INFO)

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", "8080"))

# Event для graceful shutdown
_shutdown_event = asyncio.Event()


async def on_startup(bot: Bot) -> None:
    """Устанавливаем webhook при старте и выполняем периодическое обслуживание."""
    if WEBHOOK_HOST:
        webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
        await bot.set_webhook(webhook_url)
        logging.info("Webhook установлен: %s", webhook_url)
    else:
        logging.warning("WEBHOOK_HOST не задан, webhook не установлен")

    # FIX: очистка shown_profiles при запуске (таблица растёт бесконечно)
    try:
        from repositories.profile_repo import cleanup_shown_profiles
        deleted = await cleanup_shown_profiles(max_age_days=30)
        if deleted:
            logging.info("Очищено %d старых записей shown_profiles", deleted)
    except Exception as e:
        logging.warning("Не удалось очистить shown_profiles: %s", e)


async def on_shutdown(bot: Bot) -> None:
    """Удаляем webhook при остановке."""
    await bot.delete_webhook()
    logging.info("Webhook удалён")


def _signal_handler(signum: int) -> None:
    """Обработчик сигналов SIGINT/SIGTERM для graceful shutdown."""
    logging.info("Получен сигнал %s, начинаем graceful shutdown...", signal.Signals(signum).name)
    _shutdown_event.set()


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

    # Setup application (регистрирует startup/shutdown хуки aiogram в aiohttp)
    setup_application(app, dp, bot=bot)

    # Регистрируем cleanup_ctx для graceful shutdown БД
    async def _db_cleanup_ctx(_app: web.Application):
        yield
        logging.info("Закрываю пул соединений с БД...")
        await close_db_pool()

    app.cleanup_ctx.append(_db_cleanup_ctx)

    # Регистрируем обработчики сигналов
    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signame, _signal_handler, signame)

    # Запускаем сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logging.info("Server started on port %s", PORT)

    # Ждём сигнала завершения вместо бесконечного цикла
    try:
        await _shutdown_event.wait()
    finally:
        logging.info("Останавливаю сервер...")
        await runner.cleanup()
        logging.info("Сервер остановлен")


if __name__ == "__main__":
    asyncio.run(main())
