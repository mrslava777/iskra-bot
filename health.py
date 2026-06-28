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
_shutdown_event: asyncio.Event | None = None


async def start_health_server() -> None:
    """Запускает health-сервер и держит его alive до получения сигнала остановки."""
    global _app, _runner, _shutdown_event

    port = int(os.getenv("PORT", str(Health.PORT)))
    _app = web.Application()
    _app.router.add_get("/health", _health_handler)
    _app.router.add_get("/ready", _ready_handler)

    _runner = web.AppRunner(_app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", port)
    await site.start()
    log.info("Health server started on port %s", port)

    # Ждём сигнала остановки вместо бесконечного цикла
    _shutdown_event = asyncio.Event()
    try:
        await _shutdown_event.wait()
    finally:
        log.info("Health server shutting down...")


async def stop_health_server() -> None:
    """Graceful shutdown — сигнализирует серверу остановиться."""
    global _runner, _shutdown_event
    if _shutdown_event is not None:
        _shutdown_event.set()
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
        return web.json_response({"status": "not_ready", "error": str(e)}, status=Health.HTTP_NOT_READY)
