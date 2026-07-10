"""Главный файл бота Искра — Webhook mode.

Переход с polling на webhook:
- Один aiohttp.Application обрабатывает /health, /ready, /metrics и POST /webhook
- Webhook-обновления передаются в Dispatcher через feed_raw_update()
- Семафор ограничивает одновременно обрабатываемые update'ы
- При startup регистрируется webhook, при shutdown — удаляется

Все middleware, error handlers, Sentry, Prometheus сохранены без изменений.
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

from config import BOT_TOKEN, SENTRY_DSN, WEBHOOK_URL
from database.connection import close_db_pool, ping_db, wait_until_db_ready
from handlers import setup_routers
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.nsfw_middleware import NSFWMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra.main")

PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH = "/webhook"
WEBHOOK_FULL_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

# Семафор для ограничения одновременно обрабатываемых update'ов
_update_semaphore = asyncio.Semaphore(100)


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


async def _webhook_handler(request: web.Request) -> web.Response:
    """Обработчик входящих webhook-обновлений от Telegram.

    Читает JSON-тело, передаёт update в Dispatcher через feed_raw_update().
    Семафор ограничивает количество одновременно обрабатываемых update'ов.
    """
    try:
        raw_update = await request.json()
    except Exception as e:
        log.warning("Failed to parse webhook body: %s", e)
        return web.Response(status=400, text="Bad Request")

    bot: Bot = request.app["bot"]
    dp: Dispatcher = request.app["dp"]

    async with _update_semaphore:
        try:
            await dp.feed_raw_update(bot, raw_update)
        except Exception as e:
            log.exception("Error processing webhook update: %s", e)
            # Возвращаем 200 OK, чтобы Telegram не ретраил update
            # (иначе может прийти дубль)

    return web.Response(status=200)


async def on_startup(app: web.Application) -> None:
    """Действия при запуске: прогрев БД, регистрация webhook, очистка."""
    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]

    # Ждём, пока схема прогреется
    try:
        await wait_until_db_ready(timeout=60)
        log.info("DB ready (wait_until_db_ready succeeded)")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("DB not ready after wait_until_db_ready: %s", e)

    # Регистрируем webhook
    try:
        await bot.set_webhook(
            url=WEBHOOK_FULL_URL,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("Webhook registered at %s", WEBHOOK_FULL_URL)
    except TelegramUnauthorizedError:
        log.error("Невозможно зарегистрировать webhook: токен невалиден. Проверь BOT_TOKEN.")
        raise
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("Failed to set webhook: %s", e)

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


async def on_shutdown(app: web.Application) -> None:
    """Закрываем ресурсы при остановке: удаляем webhook, закрываем сессию и БД."""
    bot: Bot = app["bot"]

    log.info("Удаляю webhook...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Webhook удалён")
    except Exception as e:
        log.warning("Failed to delete webhook: %s", e)

    log.info("Закрываю сессию бота...")
    try:
        await bot.session.close()
        log.info("Сессия бота закрыта")
    except Exception as e:
        log.warning("Failed to close bot session: %s", e)

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

    # Проверяем WEBHOOK_URL
    if not WEBHOOK_URL:
        log.error(
            "WEBHOOK_URL не задан! Проверь переменные окружения. "
            "Пример: WEBHOOK_URL=https://example.up.railway.app"
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

    # Создаём единый aiohttp Application
    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp

    # Регистрируем маршруты
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _health_handler)
    app.router.add_get("/", _health_handler)
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_post(WEBHOOK_PATH, _webhook_handler)

    # Startup / Shutdown hooks
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)

    # Запускаем сервер
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Сервер запущен на порту %s (webhook: %s)", PORT, WEBHOOK_FULL_URL)

    # Бесконечное ожидание — сервер работает пока не получит сигнал завершения
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("Получен сигнал завершения")
        raise
    finally:
        await runner.cleanup()
        log.info("Сервер остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Прервано пользователем (KeyboardInterrupt)")
    except TelegramUnauthorizedError:
        log.error("TelegramUnauthorizedError: проверь BOT_TOKEN")
        sys.exit(1)
