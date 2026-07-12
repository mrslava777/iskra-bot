"""Конфигурация бота Искра из переменных окружения."""
import logging
import os
import secrets
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("iskra.config")


def _safe_int(value: Optional[str], default: int, name: str) -> int:
    if not value:
        return default
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        log.warning("Невалидное значение %s=%r, используем default=%d", name, value, default)
        return default


def _safe_float(value: Optional[str], default: float, name: str) -> float:
    if not value:
        return default
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        log.warning("Невалидное значение %s=%r, используем default=%s", name, value, default)
        return default


def _parse_admin_ids(raw: Optional[str]) -> set[int]:
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


# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")

# Telegram разрешает 1-256 символов: A-Z, a-z, 0-9, _, -.
_webhook_secret = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
if _webhook_secret and not all(ch.isalnum() or ch in "_-" for ch in _webhook_secret):
    raise RuntimeError("WEBHOOK_SECRET_TOKEN содержит недопустимые символы")
if len(_webhook_secret) > 256:
    raise RuntimeError("WEBHOOK_SECRET_TOKEN длиннее 256 символов")
WEBHOOK_SECRET_TOKEN = _webhook_secret or secrets.token_urlsafe(32)
if not _webhook_secret:
    # Сам секрет никогда не пишем в лог.
    log.warning(
        "WEBHOOK_SECRET_TOKEN не задан: создан временный секрет. "
        "Для стабильных перезапусков задай постоянное значение в Railway."
    )

# Database
# Railway Volume должен быть смонтирован в /data.
DB_PATH = os.getenv("DB_PATH", "/data/iskra.db").strip()
DB_POOL_SIZE = max(1, _safe_int(os.getenv("DB_POOL_SIZE"), 5, "DB_POOL_SIZE"))

# Redis (опционально)
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Admin
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
if not ADMIN_IDS:
    log.warning("ADMIN_IDS не задан: админ-панель недоступна")

# Rate limiting
ANON_RATE_LIMIT_MSG_PER_MIN = max(
    1,
    _safe_int(
        os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN"),
        30,
        "ANON_RATE_LIMIT_MSG_PER_MIN",
    ),
)
MAX_TRACKED_USERS = max(
    100,
    _safe_int(os.getenv("MAX_TRACKED_USERS"), 10000, "MAX_TRACKED_USERS"),
)

# Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()

# Send queue / workers
SEND_CONCURRENCY = max(1, _safe_int(os.getenv("SEND_CONCURRENCY"), 20, "SEND_CONCURRENCY"))
NUM_WORKERS = max(1, _safe_int(os.getenv("NUM_WORKERS"), 4, "NUM_WORKERS"))
MAX_MESSAGE_RATE_GLOBAL = max(
    1,
    _safe_int(os.getenv("MAX_MESSAGE_RATE_GLOBAL"), 20, "MAX_MESSAGE_RATE_GLOBAL"),
)

# Broadcast
BROADCAST_BATCH_SIZE = max(
    1,
    _safe_int(os.getenv("BROADCAST_BATCH_SIZE"), 100, "BROADCAST_BATCH_SIZE"),
)
BROADCAST_DELAY = max(
    0.0,
    _safe_float(os.getenv("BROADCAST_DELAY"), 0.05, "BROADCAST_DELAY"),
)
BROADCAST_CONCURRENT = max(
    1,
    _safe_int(os.getenv("BROADCAST_CONCURRENT"), 10, "BROADCAST_CONCURRENT"),
)

# NSFW moderation
NSFW_API_KEY = os.getenv("NSFW_API_KEY", "").strip()
NSFW_API_PROVIDER = os.getenv("NSFW_API_PROVIDER", "").strip()
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "true").lower() in ("1", "true", "yes")
