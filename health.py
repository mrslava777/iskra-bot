"""Health-check сервер для Railway."""
import logging
import os
from aiohttp import web
from database.connection import close_db_pool
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
    await close_db_pool()


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _ready_handler(request: web.Request) -> web.Response:
    # Проверяем, что БД доступна
    try:
        from database.connection import get_db
        db = await get_db()
        await db.execute("SELECT 1")
        return web.json_response({"status": "ready"})
    except Exception as e:
        return web.json_response({"status": "not_ready", "error": str(e)}, status=Health.HTTP_NOT_READY)
