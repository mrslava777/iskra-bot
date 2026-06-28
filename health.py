"""Health-check сервер для Railway."""
import logging
import os
from aiohttp import web

from database.connection import db
from data.constants import Health

log = logging.getLogger("iskra.health")


async def start_health_server() -> None:
    port = int(os.getenv("PORT", str(Health.PORT)))
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _ready_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Health server started on port %s", port)


async def stop_health_server() -> None:
    """Graceful shutdown — пул закрывается в main.py, не здесь."""
    pass


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
