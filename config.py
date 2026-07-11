"""Конфигурация бота Искра — все переменные окружения в одном месте."""
import logging
import os
import secrets
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("iskra.config")


def _safe_int(value: Optional[str], default: int, name: str) -> int:
    """Безопасно парсит int из строки."""
    if not value:
        return default
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        log.warning("Невалидное значение %s=%r, используем default=%d", name, value, default)
        return default


def _parse_admin_ids(raw: Optional[str]) -> set[int]:
    """Парсит список ID админов из строки."""
    if not raw:
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
        elif part:
            log.warning("Невалидный ADMIN_ID: %r", part)
    return result


# ── Telegram ──────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "") 
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан! Добавь переменную окружения BOT_TOKEN. "
        "Получить токен можно у @BotFather в Telegram."
    )

# ── Webhook Security ──────────────────────────────────────────────
# FIX: secret_token для защиты webhook от подделки.
# Telegram отправляет его в заголовке X-Telegram-Bot-Api-Secret-Token.
# Если не задан — генерируем автоматически и логируем (чтобы можно было
# настроить в переменных окружения при следующем деплое).
_WEBHOOK_SECRET_RAW = os.getenv("WEBHOOK_SECRET_TOKEN", "")
if _WEBHOOK_SECRET_RAW and len(_WEBHOOK_SECRET_RAW) >= 8:
    WEBHOOK_SECRET_TOKEN = _WEBHOOK_SECRET_RAW
else:
    WEBHOOK_SECRET_TOKEN = secrets.token_urlsafe(32)
    log.warning(
        "WEBHOOK_SECRET_TOKEN не задан или слишком короткий! "
        "Сгенерирован автоматически: %s. "
        "Сохрани это значение в переменную окружения WEBHOOK_SECRET_TOKEN, "
        "чтобы оно не менялось при перезапуске.",
        WEBHOOK_SECRET_TOKEN,
    )

# ── Database ──────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "database.db")

# Redis (опционально)
REDIS_URL = os.getenv("REDIS_URL", "")

# ── Admin ─────────────────────────────────────────────────────────
ADMIN_IDS: set[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
if not ADMIN_IDS:
    log.warning("ADMIN_IDS не задан — админ-панель недоступна")

# ── Rate limiting ─────────────────────────────────────────────────
ANON_RATE_LIMIT_MSG_PER_MIN = _safe_int(
    os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN"), 30, "ANON_RATE_LIMIT_MSG_PER_MIN"
)
MAX_TRACKED_USERS = _safe_int(
    os.getenv("MAX_TRACKED_USERS"), 10000, "MAX_TRACKED_USERS"
)

# ── Sentry ────────────────────────────────────────────────────────
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Send queue / workers
SEND_CONCURRENCY = _safe_int(os.getenv("SEND_CONCURRENCY"), 20, "SEND_CONCURRENCY")
NUM_WORKERS = _safe_int(os.getenv("NUM_WORKERS"), 4, "NUM_WORKERS")
MAX_MESSAGE_RATE_GLOBAL = _safe_int(
    os.getenv("MAX_MESSAGE_RATE_GLOBAL"), 20, "MAX_MESSAGE_RATE_GLOBAL"
)

# ── Broadcast ─────────────────────────────────────────────────────
BROADCAST_BATCH_SIZE = _safe_int(
    os.getenv("BROADCAST_BATCH_SIZE"), 100, "BROADCAST_BATCH_SIZE"
)
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", "0.05"))
BROADCAST_CONCURRENT = _safe_int(
    os.getenv("BROADCAST_CONCURRENT"), 10, "BROADCAST_CONCURRENT"
)

# ── NSFW Moderation ───────────────────────────────────────────────
NSFW_API_KEY = os.getenv("NSFW_API_KEY", "")
NSFW_API_PROVIDER = os.getenv("NSFW_API_PROVIDER", "")  # sightengine | deepai | ""
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "true").lower() in ("1", "true", "yes")
