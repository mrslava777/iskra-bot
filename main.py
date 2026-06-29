"""Главный файл бота Искра — Long Polling mode.

Переход с webhook на polling:
- Убирает overhead aiohttp-сервера на каждый update
- Убирает задержку webhook → aiohttp → dispatcher → handler
- Polling забирает пачки update'ов напрямую, без HTTP-сервера
- Проще деплоить (не нужен WEBHOOK_HOST, сертификаты, etc.)
- Health-check поднимается отдельным легковесным сервером

Ожидаемый эффект: снижение latency на 100-300мс за счёт
убранного aiohttp request pipeline.

FIX v5: health-check теперь делает реальный DB ping — раннее обнаружение
        проблем с соединениями.
FIX v5: polling_timeout увеличен до 30 сек — меньше запросов к Telegram API,
        ниже нагрузка на CPU и сеть.
FIX v5: tasks_concurrency_limit=50 — предотвращает перегрузку при всплесках
        трафика (Railway free tier имеет ограничения).
"""
import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, SENTRY_DSN
from database.connection import close_db_pool, wait_until_db_ready, ping_db
from handlers import setup_routers
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra.main")

PORT = int(os.getenv("PORT", "8080"))


async def _health_handler(request: web.Request) -> web.Response:
    """Health-check с реальным DB ping.

    FIX v5: вместо статичного JSON делаем acquire + SELECT 1 из пула.
    Если соединение "мертвое", пул создаст новое — это прогревает БД
    и предотвращает 2000+ мс холодных стартов.
    """
    try:
        db_ok = await ping_db()
        if db_ok:
            return web.json_response({"status": "ok", "db": "connected"})
        else:
            return web.json_response(
                {"status": "degraded", "db": "unreachable"},
                status=503
            )
    except Exception as e:
        return web.json_response(
            {"status": "error", "detail": str(e)},
            status=503
        )


async def _metrics_handler(request: web.Request) -> web.Response:
    try:
        data = generate_latest()
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        log.exception("Failed to generate metrics: %s", e)
        return web.Response(status=500, text="error")


async def _start_health_server() -> web.AppRunner:
    """Запускает минимальный HTTP-сервер только для health-check.

    Railway требует открытый порт для проверки жизнеспособности.
    Больше ничего этот сервер не делает.
    """
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _health_handler)
    app.router.add_get("/", _health_handler)
    app.router.add_get("/metrics", _metrics_handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health-check сервер запущен на порту %s", PORT)
    return runner


async def on_startup(bot: Bot) -> None:
    """Действия при запуске: прогрев пула, очистка, удаление старого webhook."""
    # Инициализация Sentry уже выполняется в main() при старте процесса

    # Ждём, пока схема прогреется (retry/backoff handled in connection.wait_until_db_ready)
    try:
        await wait_until_db_ready(timeout=60)
        log.info("DB ready (wait_until_db_ready succeeded)")
    except Exception as e:
        log.error("DB not ready after wait_until_db_ready: %s", e)

    # Удаляем webhook если был (переход с webhook на polling)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Webhook удалён (polling mode)")
    except Exception as e:
        log.warning("Failed to delete webhook: %s", e)

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
    # Инициализируем Sentry (если задан SENTRY_DSN)
    if SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(SENTRY_DSN, traces_sample_rate=0.0)
            log.info("Sentry initialized")
        except Exception as e:
            log.warning("Failed to init Sentry: %s", e)

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
        # FIX v5: polling_timeout=30 — меньше запросов к API, ниже latency
        # FIX v5: tasks_concurrency_limit=50 — защита от перегрузки
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=True,
            polling_timeout=30,
            tasks_concurrency_limit=50,
        )
    finally:
        await health_runner.cleanup()
        log.info("Health-check сервер остановлен")


if __name__ == "__main__":
    asyncio.run(main())
