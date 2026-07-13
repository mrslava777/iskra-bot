"""Конфигурация бота Искра — все переменные окружения в одном месте."""
import logging
import os
import re
import secrets
from typing import Optional
from urllib.parse import urlparse

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


def _get_webhook_url() -> str:
    """Возвращает корректный публичный HTTPS URL для Telegram webhook.

    WEBHOOK_URL имеет приоритет. На Railway допустимо не задавать его вручную:
    после создания Public Domain используется RAILWAY_PUBLIC_DOMAIN.
    """
    raw = (os.getenv("WEBHOOK_URL") or "").strip().rstrip("/")
    if not raw:
        railway_domain = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip("/")
        if railway_domain:
            raw = f"https://{railway_domain.removeprefix('https://').removeprefix('http://')}"
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError(
            "WEBHOOK_URL должен быть публичным HTTPS-адресом без query/fragment, "
            "например https://my-bot.up.railway.app"
        )
    return raw


WEBHOOK_URL = _get_webhook_url()
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
_WEBHOOK_SECRET_RAW = (os.getenv("WEBHOOK_SECRET_TOKEN") or "").strip()
# Ограничения Telegram: 1–256 символов, только A-Z, a-z, 0-9, _ и -.
if _WEBHOOK_SECRET_RAW:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", _WEBHOOK_SECRET_RAW):
        raise RuntimeError(
            "WEBHOOK_SECRET_TOKEN должен содержать 8–256 символов: A-Z, a-z, 0-9, _ или -"
        )
    WEBHOOK_SECRET_TOKEN = _WEBHOOK_SECRET_RAW
else:
    WEBHOOK_SECRET_TOKEN = secrets.token_urlsafe(32)
    log.warning(
        "WEBHOOK_SECRET_TOKEN не задан: используется временный секрет. "
        "Добавь постоянный секрет в Railway Variables, чтобы он не менялся при перезапуске."
    )

# ── Database ──────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "database.db")
DB_POOL_SIZE = max(1, min(_safe_int(os.getenv("DB_POOL_SIZE"), 8, "DB_POOL_SIZE"), 32))

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
