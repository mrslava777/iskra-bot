"""Health-check хендлеры для Railway.

FIX: убраны неиспользуемые start_health_server() и stop_health_server() —
     main.py создаёт свой aiohttp-сервер и напрямую подключает хендлеры.
     Дублирование вызывало путаницу и оставляло мёртвый код.
"""
import logging

from aiohttp import web

from database.connection import db

log = logging.getLogger("iskra.health")


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _ready_handler(request: web.Request) -> web.Response:
    """Проверяем, что БД доступна — быстрый запрос без инициализации схемы."""
    try:
        async with db() as conn:
            await conn.execute("SELECT 1")
        return web.json_response({"status": "ready"})
    except Exception as e:
        return web.json_response({"status": "not_ready", "error": str(e)}, status=503)
