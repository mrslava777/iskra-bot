"""Главный файл бота Искра — Long Polling mode.

Переход с webhook на polling:
- Убирает overhead aiohttp-сервера на каждый update
- Убирает задержку webhook → aiohttp → dispatcher → handler
- Polling забирает пачки update'ов напрямую, без HTTP-сервера
- Проще деплоить (не нужен WEBHOOK_HOST, сертификаты, etc.)
- Health-check поднимается отдельным легковесным сервером

Ожидаемый эффект: снижение latency на 100-300мс за счёт
убранного aiohttp request pipeline.
"""
import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database.connection import close_db_pool, _get_pool, _ensure_schema
from handlers import setup_routers

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra.main")

PORT = int(os.getenv("PORT", "8080"))


async def _health_handler(request: web.Request) -> web.Response:
    """Простой health-check для Railway."""
    return web.json_response({"status": "ok"})


async def _start_health_server() -> web.AppRunner:
    """Запускает минимальный HTTP-сервер только для health-check.

    Railway требует открытый порт для проверки жизнеспособности.
    Больше ничего этот сервер не делает.
    """
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _health_handler)
    app.router.add_get("/", _health_handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health-check сервер запущен на порту %s", PORT)
    return runner


async def on_startup(bot: Bot) -> None:
    """Действия при запуске: прогрев пула, очистка, удаление старого webhook."""
    # Удаляем webhook если был (переход с webhook на polling)
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("Webhook удалён (polling mode)")

    # Прогрев пула — создаём соединения заранее, а не на первом запросе
    try:
        pool = await _get_pool()
        await _ensure_schema(pool)
        log.info("DB пул прогрет и схема готова")
    except Exception as e:
        log.error("Ошибка прогрева DB: %s", e)

    # Очистка shown_profiles
    try:
        from repositories.profile_repo import cleanup_shown_profiles
        deleted = await cleanup_shown_profiles(max_age_days=30)
        if deleted:
            log.info("Очищено %d старых записей shown_profiles", deleted)
    except Exception as e:
        log.warning("Не удалось очистить shown_profiles: %s", e)


async def on_shutdown(bot: Bot) -> None:
    """Закрываем ресурсы при остановке."""
    log.info("Закрываю пул соединений с БД...")
    await close_db_pool()
    log.info("Бот остановлен")


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Роутеры
    root_router = setup_routers()
    dp.include_router(root_router)

    # Startup/Shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Health-check сервер для Railway (отдельно от бота)
    health_runner = await _start_health_server()

    try:
        # Запускаем polling — основной цикл
        log.info("Запускаю бота в режиме long polling...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=True,
        )
    finally:
        await health_runner.cleanup()
        log.info("Health-check сервер остановлен")


if __name__ == "__main__":
    asyncio.run(main())
