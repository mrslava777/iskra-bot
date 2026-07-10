"""Главный файл бота Искра — Long Polling mode.

Переход с webhook на polling:
- Убирает overhead aiohttp-сервера на каждый update
- Убирает задержку webhook → aiohttp → dispatcher → handler
- Polling забирает пачки update'ов напрямую, без HTTP-сервера
- Проще деплоить (не нужен WEBHOOK_HOST, сертификаты, etc.)
- Health-check поднимается отдельным легковесным сервером

FIX v6: TelegramUnauthorizedError теперь ловится и выводит понятное сообщение
        вместо километрового traceback — помогает диагностировать невалидный токен.
FIX v6: cleanup_shown_profiles обёрнут в try/except — не блокирует старт при
        проблемах с параметрами aiosqlite.
FIX v7: добавлен глобальный error handler для aiogram.
        Исправлена обработка CancelledError — теперь не ловится bare except.
        Добавлены импорты TelegramRetryAfter, TelegramForbiddenError.
FIX v8: подключён RateLimitMiddleware для всех update'ов.
FIX v9: подключён NSFWMiddleware для проверки всех фото на NSFW.
"""
import asyncio
import logging
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, SENTRY_DSN
from database.connection import close_db_pool, ping_db, wait_until_db_ready
from handlers import setup_routers
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.nsfw_middleware import NSFWMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra.main")

PORT = int(os.getenv("PORT", "8080"))


async def _health_handler(request: web.Request) -> web.Response:
    """Health-check с реальным DB ping."""
    try:
        db_ok = await ping_db()
        if db_ok:
            return web.json_response({"status": "ok", "db": "connected"})
        else:
            return web.json_response(
                {"status": "degraded", "db": "unreachable"},
                status=503,
            )
    except Exception as e:
        return web.json_response(
            {"status": "error", "detail": str(e)},
            status=503,
        )


async def _metrics_handler(request: web.Request) -> web.Response:
    try:
        data = generate_latest()
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        log.exception("Failed to generate metrics: %s", e)
        return web.Response(status=500, text="error")


async def _start_health_server() -> web.AppRunner:
    """Запускает минимальный HTTP-сервер только для health-check."""
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
    # Ждём, пока схема прогреется
    try:
        await wait_until_db_ready(timeout=60)
        log.info("DB ready (wait_until_db_ready succeeded)")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("DB not ready after wait_until_db_ready: %s", e)

    # Удаляем webhook если был (переход с webhook на polling)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Webhook удалён (polling mode)")
    except TelegramUnauthorizedError:
        log.error("Невозможно удалить webhook: токен невалиден. Проверь BOT_TOKEN.")
        raise
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("Failed to delete webhook: %s", e)

    # Очистка shown_profiles
    try:
        from repositories.profile_repo import cleanup_shown_profiles

        deleted = await cleanup_shown_profiles(max_age_days=30)
        if deleted:
            log.info("Очищено %d старых записей shown_profiles", deleted)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("Не удалось очистить shown_profiles: %s", e)


async def on_shutdown(bot: Bot) -> None:
    """Закрываем ресурсы при остановке."""
    log.info("Закрываю пул соединений с БД...")
    await close_db_pool()
    log.info("Бот остановлен")


async def _global_error_handler(event: ErrorEvent) -> None:
    """Глобальный обработчик ошибок aiogram.

    Ловит необработанные исключения из хендлеров, логирует их,
    предотвращает падение бота.
    """
    exc = event.exception
    update = event.update

    if isinstance(exc, TelegramRetryAfter):
        log.warning("Flood limit exceeded, retry after %s sec", exc.retry_after)
        return
    if isinstance(exc, TelegramForbiddenError):
        log.warning("Forbidden for user, probably blocked bot: %s", exc)
        return
    if isinstance(exc, TelegramAPIError):
        log.error("Telegram API error: %s", exc)
        return
    if isinstance(exc, asyncio.CancelledError):
        # Не логируем CancelledError — это нормальное поведение при shutdown
        raise

    log.exception("Unhandled exception in handler for update %s: %s", update, exc)


async def main() -> None:
    # Инициализируем Sentry (если задан SENTRY_DSN)
    if SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(SENTRY_DSN, traces_sample_rate=0.0)
            log.info("Sentry initialized")
        except Exception as e:
            log.warning("Failed to init Sentry: %s", e)

    # Проверяем токен до создания Bot
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        log.error(
            "BOT_TOKEN не задан или слишком короткий! Проверь переменные окружения."
        )
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Роутеры
    root_router = setup_routers()
    dp.include_router(root_router)

    # Глобальный error handler
    dp.errors.register(_global_error_handler)

    # Rate limiting middleware для ВСЕХ update'ов
    dp.update.outer_middleware(RateLimitMiddleware())
    log.info("RateLimitMiddleware подключён")

    # NSFW middleware — проверяет все фото перед обработкой
    # ВАЖНО: подключаем ПОСЛЕ rate limit, чтобы не тратить API-запросы на флуд
    dp.message.outer_middleware(NSFWMiddleware())
    log.info("NSFWMiddleware подключён")

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
            polling_timeout=30,
            tasks_concurrency_limit=50,
        )
    except TelegramUnauthorizedError:
        log.error("=" * 60)
        log.error("ОШИБКА: Telegram токен невалиден (Unauthorized)")
        log.error("Проверь BOT_TOKEN в переменных окружения Railway.")
        log.error("Возможные причины:")
        log.error("  1. Токен скопирован не полностью")
        log.error("  2. Бот был удалён через @BotFather")
        log.error("  3. Токен содержит лишние пробелы или символы")
        log.error("=" * 60)
        sys.exit(1)
    except asyncio.CancelledError:
        log.info("Polling cancelled (shutdown)")
        raise
    finally:
        await health_runner.cleanup()
        log.info("Health-check сервер остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Прервано пользователем (KeyboardInterrupt)")
    except TelegramUnauthorizedError:
        # Дополнительная защита — если ошибка вылетела за пределами main()
        log.error("TelegramUnauthorizedError: проверь BOT_TOKEN")
        sys.exit(1)
