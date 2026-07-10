"""NSFW-модерация контента — автоматическая + ручная.

Уровни модерации:
  1. Эвристика: метаданные, подписи, хеши известных изображений
  2. AI-сканер: Sightengine / DeepAI / Azure Content Moderator (опционально)
  3. Пользовательские репорты: агрегация жалоб
  4. Ручная модерация админами

FIX: все внешние API-вызовы — с таймаутом и fallback.
"""
import asyncio
import hashlib
import io
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import Message, PhotoSize

from config import NSFW_API_KEY, NSFW_API_PROVIDER
from data.constants import NSFWThreshold, Message as Msg
from database.connection import db
from services.safe_send import safe_send

log = logging.getLogger("iskra.nsfw")

# ═══════════════════════════════════════════════════════════════════════════════
# КЭШ ХЕШЕЙ ЗАБАНЕННЫХ ИЗОБРАЖЕНИЙ (in-memory + DB)
# ═══════════════════════════════════════════════════════════════════════════════
_banned_hashes: set[str] = set()

async def _load_banned_hashes() -> None:
    """Загружает хеши забаненных изображений из БД."""
    try:
        async with db() as conn:
            rows = await conn.execute("SELECT image_hash FROM nsfw_banned_hashes")
            _banned_hashes.update(r[0] for r in await rows.fetchall())
    except Exception as e:
        log.warning("Failed to load banned hashes: %s", e)


def _compute_hash(photo_bytes: bytes) -> str:
    """SHA-256 хеш изображения для сравнения."""
    return hashlib.sha256(photo_bytes).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════════════════════
# AI-API ИНТЕГРАЦИИ (опционально, с graceful fallback)
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_sightengine(photo_bytes: bytes) -> tuple[float, float]:
    """Sightengine: возвращает (nudity_score, violence_score).

    https://sightengine.com/docs/
    """
    if not NSFW_API_KEY or NSFW_API_PROVIDER != "sightengine":
        return 0.0, 0.0

    import aiohttp
    api_user, api_secret = NSFW_API_KEY.split(":", 1)

    data = aiohttp.FormData()
    data.add_field("media", io.BytesIO(photo_bytes), filename="photo.jpg")
    data.add_field("api_user", api_user)
    data.add_field("api_secret", api_secret)
    data.add_field("models", "nudity-2.1,weapon,violence,offensive")

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post("https://api.sightengine.com/1.0/check.json", data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    nudity = result.get("nudity", {})
                    # score от 0 до 1, где 1 = точно NSFW
                    score = max(
                        nudity.get("sexual_activity", 0),
                        nudity.get("sexual_display", 0),
                        nudity.get("erotica", 0),
                    )
                    violence = result.get("violence", {}).get("prob", 0)
                    return score, violence
    except asyncio.TimeoutError:
        log.warning("Sightengine timeout")
    except Exception as e:
        log.warning("Sightengine error: %s", e)
    return 0.0, 0.0


async def _check_deepai(photo_bytes: bytes) -> float:
    """DeepAI NSFW detector. Возвращает score 0-1."""
    if not NSFW_API_KEY or NSFW_API_PROVIDER != "deepai":
        return 0.0

    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            data = aiohttp.FormData()
            data.add_field("image", io.BytesIO(photo_bytes), filename="photo.jpg")
            async with session.post(
                "https://api.deepai.org/api/nsfw-detector",
                data=data,
                headers={"api-key": NSFW_API_KEY},
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    detections = result.get("output", {}).get("detections", [])
                    if detections:
                        return max(d.get("confidence", 0) for d in detections)
    except asyncio.TimeoutError:
        log.warning("DeepAI timeout")
    except Exception as e:
        log.warning("DeepAI error: %s", e)
    return 0.0


async def _ai_check(photo_bytes: bytes) -> tuple[float, float]:
    """Запускает AI-проверку. Возвращает (nsfw_score, violence_score)."""
    if NSFW_API_PROVIDER == "sightengine":
        return await _check_sightengine(photo_bytes)
    elif NSFW_API_PROVIDER == "deepai":
        score = await _check_deepai(photo_bytes)
        return score, 0.0
    return 0.0, 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# ЭВРИСТИЧЕСКАЯ ПРОВЕРКА
# ═══════════════════════════════════════════════════════════════════════════════

async def _heuristic_check(
    photo_bytes: bytes,
    caption: Optional[str] = None,
) -> tuple[bool, str]:
    """Быстрая эвристика без внешних API.

    Returns: (is_nsfw, reason)
    """
    # 1. Проверка по хешу
    img_hash = _compute_hash(photo_bytes)
    if img_hash in _banned_hashes:
        return True, "hash_match"

    # 2. Проверка подписи на запрещённые слова
    if caption:
        banned_words = {"xxx", "porn", "nude", "naked", "sex", "18+", "onlyfans"}
        caption_lower = caption.lower()
        for word in banned_words:
            if word in caption_lower:
                return True, f"caption_banned_word:{word}"

    return False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ФУНКЦИЯ ПРОВЕРКИ
# ═══════════════════════════════════════════════════════════════════════════════

async def check_photo(
    bot: Bot,
    message: Message,
    photo: Optional[PhotoSize] = None,
) -> tuple[bool, dict]:
    """Проверяет фото на NSFW-контент.

    Returns:
        (is_blocked, details_dict)
        details: {reason, score, ai_score, hash_match, action_taken}
    """
    if photo is None and message.photo:
        photo = message.photo[-1]  # highest resolution

    if not photo:
        return False, {"reason": "no_photo"}

    # Скачиваем фото
    try:
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
    except Exception as e:
        log.warning("Failed to download photo for NSFW check: %s", e)
        return False, {"reason": "download_error"}

    # 1. Эвристика
    is_nsfw, reason = await _heuristic_check(photo_bytes, message.caption)
    if is_nsfw:
        await _take_action(message, reason, photo_bytes)
        return True, {"reason": reason, "action": "blocked"}

    # 2. AI-проверка (если настроена)
    nsfw_score, violence_score = await _ai_check(photo_bytes)
    details = {
        "ai_nsfw_score": round(nsfw_score, 3),
        "ai_violence_score": round(violence_score, 3),
    }

    if nsfw_score >= NSFWThreshold.NUDITY or violence_score >= NSFWThreshold.VIOLENCE:
        await _take_action(message, f"ai_score:{nsfw_score:.2f}", photo_bytes)
        details["action"] = "blocked"
        return True, details

    # 3. Подозрительно, но не критично — логируем для ручной проверки
    if nsfw_score >= NSFWThreshold.SUSPICIOUS:
        await _log_suspicious(message, nsfw_score, photo_bytes)
        details["action"] = "flagged_for_review"
    else:
        details["action"] = "passed"

    return False, details


async def _take_action(message: Message, reason: str, photo_bytes: bytes) -> None:
    """Блокирует контент и наказывает пользователя."""
    tg_id = message.from_user.id

    # Удаляем сообщение
    try:
        await message.delete()
    except Exception as e:
        log.debug("Could not delete NSFW message: %s", e)

    # Уведомляем пользователя
    try:
        await safe_send(
            message.answer(Msg.NSFW_BLOCKED),
            log_prefix="nsfw_notify",
        )
    except Exception:
        pass

    # Сохраняем хеш для будущих проверок
    img_hash = _compute_hash(photo_bytes)
    _banned_hashes.add(img_hash)
    try:
        async with db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO nsfw_banned_hashes (image_hash, reason, created_at) VALUES (?, ?, ?)",
                (img_hash, reason, int(asyncio.get_event_loop().time())),
            )
    except Exception as e:
        log.warning("Failed to save banned hash: %s", e)

    # Инкрементим счётчик нарушений пользователя
    try:
        async with db() as conn:
            await conn.execute(
                "UPDATE users SET nsfw_strikes = COALESCE(nsfw_strikes, 0) + 1 WHERE tg_id = ?",
                (tg_id,),
            )
            # Проверяем, не пора ли банить
            cursor = await conn.execute(
                "SELECT nsfw_strikes FROM users WHERE tg_id = ?", (tg_id,)
            )
            row = await cursor.fetchone()
            if row and row[0] >= NSFWThreshold.AUTO_BAN_STRIKES:
                await conn.execute(
                    "UPDATE users SET is_banned = 1 WHERE tg_id = ?", (tg_id,)
                )
                log.warning("User %d auto-banned for %d NSFW strikes", tg_id, row[0])
    except Exception as e:
        log.error("Failed to update NSFW strikes: %s", e)


async def _log_suspicious(message: Message, score: float, photo_bytes: bytes) -> None:
    """Логирует подозрительный контент для ручной проверки."""
    try:
        async with db() as conn:
            await conn.execute(
                """INSERT INTO nsfw_review_queue 
                   (tg_id, message_id, chat_id, ai_score, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message.from_user.id, message.message_id, message.chat.id,
                 score, "pending", int(asyncio.get_event_loop().time())),
            )
    except Exception as e:
        log.debug("Failed to log suspicious content: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# ПУБЛИЧНЫЕ API ДЛЯ ХЕНДЛЕРОВ
# ═══════════════════════════════════════════════════════════════════════════════

async def moderate_photo_message(bot: Bot, message: Message) -> bool:
    """Хендлер-обёртка: проверяет фото в сообщении.

    Returns True если сообщение заблокировано.
    """
    if not message.photo:
        return False
    blocked, details = await check_photo(bot, message)
    if blocked:
        log.info("NSFW blocked from user %d: %s", message.from_user.id, details)
    return blocked


async def moderate_profile_photo(bot: Bot, tg_id: int, photo_file_id: str) -> tuple[bool, str]:
    """Проверяет фото анкеты перед сохранением.

    Returns: (is_allowed, reason)
    """
    try:
        file = await bot.get_file(photo_file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
    except Exception as e:
        log.warning("Failed to download profile photo: %s", e)
        return True, ""  # fallback: разрешаем если не смогли проверить

    is_nsfw, reason = await _heuristic_check(photo_bytes)
    if is_nsfw:
        return False, reason

    nsfw_score, _ = await _ai_check(photo_bytes)
    if nsfw_score >= NSFWThreshold.NUDITY:
        return False, f"ai_nsfw:{nsfw_score:.2f}"

    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# МИГРАЦИЯ: таблицы NSFW-модерации
# ═══════════════════════════════════════════════════════════════════════════════

NSFW_MIGRATION_SQL = """
-- Таблица забаненных хешей изображений
CREATE TABLE IF NOT EXISTS nsfw_banned_hashes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_hash  TEXT UNIQUE NOT NULL,
    reason      TEXT,
    created_at  INTEGER DEFAULT (strftime('%s','now'))
);

-- Таблица подозрительного контента на ручную проверку
CREATE TABLE IF NOT EXISTS nsfw_review_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    message_id  INTEGER,
    chat_id     INTEGER,
    ai_score    REAL,
    status      TEXT DEFAULT 'pending',  -- pending, approved, rejected
    reviewed_by INTEGER,
    created_at  INTEGER DEFAULT (strftime('%s','now')),
    reviewed_at INTEGER
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_nsfw_hash ON nsfw_banned_hashes(image_hash);
CREATE INDEX IF NOT EXISTS idx_nsfw_review_status ON nsfw_review_queue(status);
CREATE INDEX IF NOT EXISTS idx_nsfw_review_user ON nsfw_review_queue(tg_id);

-- Колонка nsfw_strikes в users (если ещё нет)
ALTER TABLE users ADD COLUMN nsfw_strikes INTEGER DEFAULT 0;
"""
