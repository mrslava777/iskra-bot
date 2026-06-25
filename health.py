"""Health-check сервер для Railway."""
import asyncio
import logging
import os
from aiohttp import web

log = logging.getLogger("iskra.health")


async def start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Health server started on port %s", port)


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})
