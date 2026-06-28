"""Health-check сервер для Railway."""
import asyncio
import logging
import os
from aiohttp import web

from database.connection import db
from data.constants import Health

log = logging.getLogger("iskra.health")

_app: web.Application | None = None
_runner: web.AppRunner | None = None
_site: web.TCPSite | None = None


async def start_health_server() -> None:
    """Запускает health-сервер."""
    global _app, _runner, _site

    port = int(os.getenv("PORT", str(Health.PORT)))
    _app = web.Application()
    _app.router.add_get("/health", _health_handler)
    _app.router.add_get("/ready", _ready_handler)

    _runner = web.AppRunner(_app)
    await _runner.setup()
    _site = web.TCPSite(_runner, "0.0.0.0", port)
    await _site.start()
    log.info("Health server started on port %s", port)

    # Просто ждём, пока не будет вызван stop_health_server
    # НЕ используем бесконечный цикл — AppRunner сам держит сервер
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("Health server task cancelled")
        raise


async def stop_health_server() -> None:
    """Graceful shutdown."""
    global _runner
    if _runner is not None:
        await _runner.cleanup()
        _runner = None
        log.info("Health server stopped")


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _ready_handler(request: web.Request) -> web.Response:
    """Проверяем, что БД доступна — быстрый запрос без инициализации схемы."""
    try:
        async with db() as conn:
            await conn.execute("SELECT 1")
        return web.json_response({"status": "ready"})
    except Exception as e:
        log.error("Health check failed: %s", e)
        return web.json_response({"status": "not_ready", "error": str(e)}, status=Health.HTTP_NOT_READY)
