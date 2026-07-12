"""Главный файл бота Искра: aiohttp webhook-сервер."""
import asyncio
import logging
import os
import secrets
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
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from config import (
    BOT_TOKEN,
    REDIS_URL,
    SENTRY_DSN,
    WEBHOOK_SECRET_TOKEN,
    WEBHOOK_URL,
)
from database.connection import close_db_pool, ping_db, wait_until_db_ready
from handlers import setup_routers
from middlewares.nsfw_middleware import NSFWMiddleware
from middlewares.rate_limit import RateLimitMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra.main")

PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH = "/webhook"
_update_semaphore = asyncio.Semaphore(100)


def _build_storage():
    """Redis при заданном REDIS_URL, иначе MemoryStorage."""
    if not REDIS_URL:
        log.warning("REDIS_URL не задан: FSM-состояния теряются при рестарте")
        return MemoryStorage()

    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except Exception as exc:
        # Если Redis явно настроен, тихий fallback опасен: бот выглядит рабочим,
        # но пользователи теряют состояния при каждом рестарте.
        raise RuntimeError("Redis настроен, но RedisStorage недоступен") from exc

    log.info("FSM storage: Redis")
    return RedisStorage.from_url(REDIS_URL)


def _webhook_full_url() -> str:
    return f"{WEBHOOK_URL}{WEBHOOK_PATH}"


async def _health_handler(request: web.Request) -> web.Response:
    try:
        if await ping_db():
            return web.json_response({"status": "ok", "db": "connected"})
        return web.json_response(
            {"status": "degraded", "db": "unreachable"},
            status=503,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Не отдаём наружу пути, SQL и другие внутренние детали исключения.
        log.exception("Health check failed")
        return web.json_response({"status": "error"}, status=503)


async def _metrics_handler(request: web.Request) -> web.Response:
    try:
        return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)
    except Exception:
        log.exception("Failed to generate metrics")
        return web.Response(status=500, text="error")


async def _webhook_handler(request: web.Request) -> web.Response:
    supplied_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        "",
    )
    if not secrets.compare_digest(supplied_secret, WEBHOOK_SECRET_TOKEN):
        # Никогда не логируем ни присланный, ни ожидаемый секрет целиком/частично.
        log.warning("Webhook rejected: invalid secret from %s", request.remote)
        return web.Response(status=401, text="Unauthorized")

    try:
        raw_update = await request.json()
    except Exception:
        log.warning("Webhook rejected: invalid JSON from %s", request.remote)
        return web.Response(status=400, text="Bad Request")

    bot: Bot = request.app["bot"]
    dp: Dispatcher = request.app["dp"]

    async with _update_semaphore:
        try:
            await dp.feed_raw_update(bot, raw_update)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Возвращаем 200, чтобы Telegram не создавал бесконечные дубли
            # одного и того же повреждённого update.
            log.exception("Error processing webhook update")

    return web.Response(status=200)


async def on_startup(app: web.Application) -> None:
    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]

    # Бот не должен выглядеть healthy с нерабочей БД.
    await wait_until_db_ready(timeout=60)
    log.info("DB ready")

    # Ошибка регистрации webhook должна сорвать запуск, иначе контейнер будет
    # зелёным, но Telegram не сможет присылать события.
    await bot.set_webhook(
        url=_webhook_full_url(),
        secret_token=WEBHOOK_SECRET_TOKEN,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    log.info("Webhook registered at %s", _webhook_full_url())

    try:
        from repositories.profile_repo import cleanup_shown_profiles

        deleted = await cleanup_shown_profiles(max_age_days=30)
        if deleted:
            log.info("Очищено %d старых записей shown_profiles", deleted)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Очистка не критична для запуска.
        log.exception("Не удалось очистить shown_profiles")


async def on_shutdown(app: web.Application) -> None:
    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]

    # ВАЖНО: не вызываем delete_webhook(). При rolling deploy старый контейнер
    # часто останавливается после запуска нового и удалял бы только что
    # зарегистрированный новым контейнером webhook.
    try:
        await dp.storage.close()
    except Exception as exc:
        log.debug("Storage close failed: %s", exc)

    try:
        await bot.session.close()
    except Exception as exc:
        log.warning("Failed to close bot session: %s", exc)

    await close_db_pool()
    log.info("Бот остановлен")


async def _global_error_handler(event: ErrorEvent) -> None:
    exc = event.exception

    if isinstance(exc, TelegramRetryAfter):
        log.warning("Flood limit exceeded, retry after %s sec", exc.retry_after)
        return
    if isinstance(exc, TelegramForbiddenError):
        log.warning("User blocked the bot: %s", exc)
        return
    if isinstance(exc, TelegramAPIError):
        log.error("Telegram API error: %s", exc)
        return
    if isinstance(exc, asyncio.CancelledError):
        raise exc

    log.exception("Unhandled handler exception: %s", exc)


async def main() -> None:
    if SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(SENTRY_DSN, traces_sample_rate=0.0)
            log.info("Sentry initialized")
        except Exception as exc:
            log.warning("Failed to init Sentry: %s", exc)

    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        log.error("BOT_TOKEN не задан или слишком короткий")
        raise SystemExit(1)

    if not WEBHOOK_URL or not WEBHOOK_URL.startswith(("https://", "http://")):
        log.error("WEBHOOK_URL не задан или имеет неверный формат")
        raise SystemExit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=_build_storage())

    dp.include_router(setup_routers())
    dp.errors.register(_global_error_handler)
    dp.update.outer_middleware(RateLimitMiddleware())
    dp.message.outer_middleware(NSFWMiddleware())

    app = web.Application(client_max_size=1024 * 1024)
    app["bot"] = bot
    app["dp"] = dp

    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _health_handler)
    app.router.add_get("/", _health_handler)
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_post(WEBHOOK_PATH, _webhook_handler)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Сервер запущен на порту %s", PORT)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("Получен сигнал завершения")
        raise
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Прервано пользователем")
    except TelegramUnauthorizedError:
        log.error("Telegram отклонил BOT_TOKEN")
        raise SystemExit(1)
