"""Лёгкий HTTP-healthcheck для мониторинга Искры.

Бот работает на long polling и сам по себе не поднимает HTTP-сервер, поэтому
снаружи «пингануть» его нельзя. Этот модуль поднимает крошечный отдельный
веб-сервер с эндпоинтом ``/health`` в том же event loop, что и поллинг:

- пока процесс жив и event loop крутится — фоновая задача heartbeat обновляет
  отметку времени, и ``/health`` отдаёт 200;
- если процесс упал/перезапускается — порт недоступен (connection refused);
- если event loop завис — heartbeat перестаёт обновляться и ``/health`` отдаёт
  503 ``stale``.

Логику бота модуль не трогает и при любой своей ошибке не должен ронять бота.
"""
import asyncio
import logging
import os
import time

from aiohttp import web

log = logging.getLogger("iskra.health")

# Сколько секунд без heartbeat считаем «завис»
STALE_AFTER = int(os.getenv("HEALTH_STALE_AFTER", "120"))
# Период heartbeat
BEAT_INTERVAL = int(os.getenv("HEALTH_BEAT_INTERVAL", "30"))

_state = {"started_at": time.time(), "last_beat": time.time()}


def mark_alive() -> None:
    """Отметить, что бот жив (вызывается heartbeat'ом и на каждом апдейте)."""
    _state["last_beat"] = time.time()


async def _heartbeat() -> None:
    while True:
        mark_alive()
        await asyncio.sleep(BEAT_INTERVAL)


async def _health(_request: web.Request) -> web.Response:
    now = time.time()
    age = now - _state["last_beat"]
    healthy = age < STALE_AFTER
    return web.json_response(
        {
            "status": "ok" if healthy else "stale",
            "uptime_seconds": int(now - _state["started_at"]),
            "seconds_since_last_beat": int(age),
        },
        status=200 if healthy else 503,
    )


async def start_health_server() -> None:
    """Поднять /health сервер и фоновый heartbeat. Не роняет бота при ошибке."""
    try:
        port = int(os.getenv("PORT", "8080"))
        app = web.Application()
        app.router.add_get("/health", _health)
        app.router.add_get("/", _health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        asyncio.create_task(_heartbeat())
        log.info("✅ Healthcheck доступен на :%s/health", port)
    except Exception as exc:  # noqa: BLE001 — мониторинг не должен ломать бота
        log.warning("⚠️ Не удалось поднять healthcheck-сервер: %s", exc)
