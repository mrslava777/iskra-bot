"""Конфигурация бота Искра — все переменные окружения в одном месте."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Добавь переменную окружения BOT_TOKEN")

# ── Database ──────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
PGBOUNCER_URL = os.getenv("PGBOUNCER_URL", "")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

# Redis
REDIS_URL = os.getenv("REDIS_URL", "")

# ── Admin ─────────────────────────────────────────────────────────
ADMIN_IDS = set(
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
)

# ── Rate limiting ─────────────────────────────────────────────────
ANON_RATE_LIMIT_MSG_PER_MIN = int(os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN", "30"))
MAX_TRACKED_USERS = int(os.getenv("MAX_TRACKED_USERS", "10000"))

# ── Sentry ────────────────────────────────────────────────────────
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Send queue / workers
SEND_CONCURRENCY = int(os.getenv("SEND_CONCURRENCY", "20"))
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "4"))
MAX_MESSAGE_RATE_GLOBAL = int(os.getenv("MAX_MESSAGE_RATE_GLOBAL", "20"))

# ── Broadcast ─────────────────────────────────────────────────────
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", "100"))
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", "0.05"))
BROADCAST_CONCURRENT = int(os.getenv("BROADCAST_CONCURRENT", "10"))
