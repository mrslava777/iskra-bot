"""HTTP-сервер: healthcheck + Admin API для веб-панели.

Поднимается в том же event loop, что и поллинг бота.
"""
import asyncio
import json
import logging
import os
import time

from aiohttp import web

import database as db

log = logging.getLogger("iskra.health")

# Сколько секунд без heartbeat считаем «завис»
STALE_AFTER = int(os.getenv("HEALTH_STALE_AFTER", "120"))
# Период heartbeat
BEAT_INTERVAL = int(os.getenv("HEALTH_BEAT_INTERVAL", "30"))
# Секрет для API (ставится в Railway Variables)
API_SECRET = os.getenv("API_SECRET", "")

_state = {"started_at": time.time(), "last_beat": time.time()}


def mark_alive() -> None:
    """Отметить, что бот жив (вызывается heartbeat'ом и на каждом апдейте)."""
    _state["last_beat"] = time.time()


async def _heartbeat() -> None:
    while True:
        mark_alive()
        await asyncio.sleep(BEAT_INTERVAL)


# ── Middleware: CORS + API auth ────────────────────────────────────

def _check_api_auth(request: web.Request) -> bool:
    """Проверка токена для /api/* эндпоинтов."""
    if not API_SECRET:
        return False  # API отключён если секрет не задан
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return token == API_SECRET


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return resp


# ── Health ─────────────────────────────────────────────────────────

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


# ── Admin API endpoints ───────────────────────────────────────────

def _api_error(msg: str, status: int = 401) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def api_stats(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    s = await db.stats()
    ext = await db.admin_extended_stats()
    return web.json_response({**s, **ext})


async def api_users(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    page = int(request.query.get("page", "1"))
    limit = min(int(request.query.get("limit", "50")), 100)
    search = request.query.get("search", "").strip()
    offset = (page - 1) * limit

    conn = await db.get_db()
    if search:
        cur = await conn.execute(
            """SELECT * FROM users WHERE name IS NOT NULL
               AND (name LIKE ? OR username LIKE ? OR CAST(tg_id AS TEXT) LIKE ?)
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (f"%{search}%", f"%{search}%", f"%{search}%", limit, offset),
        )
        count_cur = await conn.execute(
            """SELECT COUNT(*) c FROM users WHERE name IS NOT NULL
               AND (name LIKE ? OR username LIKE ? OR CAST(tg_id AS TEXT) LIKE ?)""",
            (f"%{search}%", f"%{search}%", f"%{search}%"),
        )
    else:
        cur = await conn.execute(
            "SELECT * FROM users WHERE name IS NOT NULL ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        count_cur = await conn.execute(
            "SELECT COUNT(*) c FROM users WHERE name IS NOT NULL"
        )
    rows = await cur.fetchall()
    total_row = await count_cur.fetchone()
    total = total_row["c"] if total_row else 0

    users = []
    for r in rows:
        users.append({
            "tg_id": r["tg_id"],
            "username": r["username"],
            "name": r["name"],
            "age": r["age"],
            "gender": r["gender"],
            "seeking": r["seeking"],
            "city": r["city"],
            "bio": r["bio"],
            "interests": r["interests"],
            "active": bool(r["active"]),
            "is_banned": bool(r["is_banned"]),
            "rating": r["rating"],
            "streak": r["streak"],
            "verified": bool(r["verified"]) if r["verified"] else False,
            "created_at": r["created_at"],
            "last_active": r["last_active"],
        })

    return web.json_response({
        "users": users,
        "total": total,
        "page": page,
        "limit": limit,
    })


async def api_reports(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    conn = await db.get_db()
    cur = await conn.execute(
        """SELECT r.to_id, COUNT(*) AS report_count, MAX(r.created_at) AS last_report,
                  u.name, u.username, u.is_banned
           FROM reports r
           LEFT JOIN users u ON u.tg_id = r.to_id
           GROUP BY r.to_id
           ORDER BY last_report DESC
           LIMIT 50"""
    )
    rows = await cur.fetchall()
    reports = []
    for r in rows:
        reports.append({
            "to_id": r["to_id"],
            "report_count": r["report_count"],
            "last_report": r["last_report"],
            "name": r["name"],
            "username": r["username"],
            "is_banned": bool(r["is_banned"]) if r["is_banned"] is not None else False,
        })
    return web.json_response({"reports": reports})


async def api_ban(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        tg_id = int(data["tg_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {\"tg_id\": 123}", 400)
    user = await db.get_user(tg_id)
    if not user:
        return _api_error("user not found", 404)
    await db.admin_ban_user(tg_id)
    return web.json_response({"ok": True, "tg_id": tg_id, "action": "banned"})


async def api_unban(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        tg_id = int(data["tg_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {\"tg_id\": 123}", 400)
    user = await db.get_user(tg_id)
    if not user:
        return _api_error("user not found", 404)
    await db.admin_unban_user(tg_id)
    return web.json_response({"ok": True, "tg_id": tg_id, "action": "unbanned"})


async def api_unverify(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        tg_id = int(data["tg_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {\"tg_id\": 123}", 400)
    user = await db.get_user(tg_id)
    if not user:
        return _api_error("user not found", 404)
    await db.upsert_user(tg_id, verified=0)
    return web.json_response({"ok": True, "tg_id": tg_id, "action": "unverified"})



async def api_tickets(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    status = request.query.get("status", "").strip() or None
    page = int(request.query.get("page", "1"))
    limit = min(int(request.query.get("limit", "50")), 100)
    offset = (page - 1) * limit
    rows = await db.get_tickets(status=status, limit=limit, offset=offset)
    total = await db.tickets_count(status=status)
    tickets = []
    for r in rows:
        tickets.append({
            "id": r["id"],
            "tg_id": r["tg_id"],
            "name": r["name"],
            "username": r["username"],
            "category": r["category"],
            "message": r["message"],
            "status": r["status"],
            "admin_reply": r["admin_reply"],
            "created_at": r["created_at"],
            "replied_at": r["replied_at"],
        })
    return web.json_response({"tickets": tickets, "total": total, "page": page, "limit": limit})


async def api_ticket_reply(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        ticket_id = int(data["id"])
        reply_text = data["reply"].strip()
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {id, reply}", 400)
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        return _api_error("ticket not found", 404)
    await db.reply_ticket(ticket_id, reply_text)
    # Send reply to user via bot
    try:
        from bot import bot as tg_bot
        await tg_bot.send_message(
            ticket["tg_id"],
            f"\U0001f4ac <b>Ответ от поддержки:</b>\n\n{reply_text}",
        )
    except Exception:
        pass
    return web.json_response({"ok": True, "id": ticket_id})


async def api_ticket_close(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        ticket_id = int(data["id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {id}", 400)
    await db.close_ticket(ticket_id)
    return web.json_response({"ok": True, "id": ticket_id})


async def api_ticket_delete(request: web.Request) -> web.Response:
    if not _check_api_auth(request):
        return _api_error("unauthorized")
    try:
        data = await request.json()
        ticket_id = int(data["id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return _api_error("bad request: need {id}", 400)
    await db.delete_ticket(ticket_id)
    return web.json_response({"ok": True, "id": ticket_id})

# ── Server startup ─────────────────────────────────────────────────

async def start_health_server() -> None:
    """Поднять /health + Admin API сервер и фоновый heartbeat."""
    try:
        port = int(os.getenv("PORT", "8080"))
        app = web.Application(middlewares=[cors_middleware])

        # Health
        app.router.add_get("/health", _health)
        app.router.add_get("/", _health)

        # Admin API
        app.router.add_get("/api/stats", api_stats)
        app.router.add_get("/api/users", api_users)
        app.router.add_get("/api/reports", api_reports)
        app.router.add_post("/api/ban", api_ban)
        app.router.add_post("/api/unban", api_unban)
        app.router.add_post("/api/unverify", api_unverify)

        # Tickets API
        app.router.add_get("/api/tickets", api_tickets)
        app.router.add_post("/api/ticket/reply", api_ticket_reply)
        app.router.add_post("/api/ticket/close", api_ticket_close)
        app.router.add_post("/api/ticket/delete", api_ticket_delete)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        asyncio.create_task(_heartbeat())
        api_status = "включён" if API_SECRET else "ВЫКЛЮЧЕН (задай API_SECRET)"
        log.info("✅ Сервер на :%s — health + API (%s)", port, api_status)
    except Exception as exc:  # noqa: BLE001
        log.warning("⚠️ Не удалось поднять сервер: %s", exc)
