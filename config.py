"""Конфигурация бота Искра.

Все переменные загружаются из окружения (.env или Railway Variables).
"""
import os

# ── Telegram ──────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Webhook ───────────────────────────────────────────────────────
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Пример: https://example.up.railway.app

# ── Database ──────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "./iskra.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")

# ── Redis (опционально) ─────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL")

# ── NSFW API (опционально) ──────────────────────────────────────
NSFW_API_KEY = os.getenv("NSFW_API_KEY")
NSFW_API_PROVIDER = os.getenv("NSFW_API_PROVIDER", "sightengine")  # sightengine | deepai

# ── Admin IDs ─────────────────────────────────────────────────────
ADMIN_IDS = set()
_raw_admins = os.getenv("ADMIN_IDS", "")
if _raw_admins:
    ADMIN_IDS = {int(x.strip()) for x in _raw_admins.split(",") if x.strip().isdigit()}

# ── Rate Limiting ─────────────────────────────────────────────────
ANON_RATE_LIMIT_MSG_PER_MIN = int(os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN", "30"))
MAX_TRACKED_USERS = int(os.getenv("MAX_TRACKED_USERS", "10000"))

# ── Sentry ────────────────────────────────────────────────────────
SENTRY_DSN = os.getenv("SENTRY_DSN")
