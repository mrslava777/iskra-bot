"""NSFW-модерация контента — автоматическая + ручная.

Уровни модерации:
 1. Эвристика: хеши известных изображений, запрещённые слова в подписи
 2. AI-сканер изображений: Sightengine nudity-2.1 / DeepAI
 3. AI-модерация текста: Sightengine Text Moderation (ML + rules)
 4. Ручная модерация админами

FIX v13: скоринг фото под nudity-2.1 (ловит раздетость, не режет пляж).
FIX v14: _check_sightengine_text переписан под реальный ответ API —
 отдельно ML (moderation_classes) и rules (profanity.matches).
 Русский язык включён (lang=ru,en). Порог ML вынесен в TEXT_ML_THRESHOLD.
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

_banned_hashes: set[str] = set()

# Порог ML-классов текста (sexual/insulting/violent/toxic/...). 0..1.
TEXT_ML_THRESHOLD = 0.5


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


def _score_nudity(nudity: dict) -> float:
    """Итоговый nudity-score из ответа Sightengine nudity-2.1.

    Явный контент + раздетость (бельё, обнажёнка, арт-ню, секс-игрушки) блокируем.
    Пляжные bikini / swimwear / cleavage разрешаем (норм для анкет).
    """
    sc = nudity.get("suggestive_classes", {}) or {}

    explicit = max(
        nudity.get("sexual_activity", 0.0),
        nudity.get("sexual_display", 0.0),
        nudity.get("erotica", 0.0),
        nudity.get("raw", 0.0),
    )
    undressed = max(
        sc.get("visibly_undressed", 0.0),
        sc.get("lingerie", 0.0),
        sc.get("male_underwear", 0.0),
        sc.get("nudity_art", 0.0),
        sc.get("sextoy", 0.0),
        sc.get("suggestive_pose", 0.0) * 0.6,
    )
    score = max(explicit, undressed, nudity.get("very_suggestive", 0.0) * 0.85)

    allowed = max(
        sc.get("bikini", 0.0),
        sc.get("swimwear_one_piece", 0.0),
        sc.get("swimwear_male", 0.0),
        sc.get("cleavage", 0.0),
        sc.get("miniskirt", 0.0),
        sc.get("minishort", 0.0),
    )
    none_score = nudity.get("none", 1.0)
    if none_score < 0.5 and allowed < 0.5:
        score = max(score, 1.0 - none_score)

    return min(score, 1.0)


async def _check_sightengine(photo_bytes: bytes) -> tuple[float, float]:
    """Sightengine (image): возвращает (nudity_score, violence_score)."""
    log.info("Sightengine check started. API_KEY set=%s, provider=%s",
             bool(NSFW_API_KEY), NSFW_API_PROVIDER)

    if not NSFW_API_KEY or NSFW_API_PROVIDER != "sightengine":
        log.warning("Sightengine skipped: key=%s provider=%s",
                    bool(NSFW_API_KEY), NSFW_API_PROVIDER)
        return 0.0, 0.0

    try:
        api_user, api_secret = NSFW_API_KEY.split(":", 1)
    except ValueError as e:
        log.error("Failed to parse NSFW_API_KEY (expected user:secret): %s", e)
        return 0.0, 0.0

    import aiohttp

    data = aiohttp.FormData()
    data.add_field("media", io.BytesIO(photo_bytes), filename="photo.jpg")
    data.add_field("api_user", api_user)
    data.add_field("api_secret", api_secret)
    data.add_field("models", "nudity-2.1,weapon,violence,offensive")

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post("https://api.sightengine.com/1.0/check.json", data=data) as resp:
                log.info("Sightengine response status: %s", resp.status)
                if resp.status == 200:
                    result = await resp.json()
                    log.info("Sightengine raw response: %s", result)
                    nudity = result.get("nudity", {})
                    score = _score_nudity(nudity)
                    violence = result.get("violence", {}).get("prob", 0)
                    log.info("Sightengine scores: nudity=%.3f, violence=%.3f", score, violence)
                    return score, violence
                else:
                    body = await resp.text()
                    log.warning("Sightengine error status=%s body=%s", resp.status, body[:200])
    except asyncio.TimeoutError:
        log.warning("Sightengine timeout")
    except Exception as e:
        log.warning("Sightengine error: %s", e)
    return 0.0, 0.0


async def _check_sightengine_text(text: str) -> tuple[bool, dict]:
    """Sightengine Text Moderation (ML + rules).

    Returns: (is_blocked, details)

    ML-модели (general, self-harm) → moderation_classes со скорами 0..1.
    Rules-модель → profanity.matches (готовый список брани по языкам).
    Блокируем, если сработал профанити-словарь ИЛИ любой ML-класс >= порога.
    """
    if not NSFW_API_KEY or NSFW_API_PROVIDER != "sightengine":
        return False, {"reason": "no_api_config"}

    try:
        api_user, api_secret = NSFW_API_KEY.split(":", 1)
    except ValueError:
        log.error("Failed to parse NSFW_API_KEY (expected user:secret)")
        return False, {"reason": "bad_api_key_format"}

    import aiohttp

    data = {
        "text": text,
        "lang": "ru,en",              # русский + английский
        "mode": "ml,rules",           # ML + встроенный профанити-словарь
        "models": "general,self-harm",
        "api_user": api_user,
        "api_secret": api_secret,
    }

    log.info("Sightengine text check: text_len=%d", len(text))
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post(
                "https://api.sightengine.com/1.0/text/check.json",
                data=data,
            ) as resp:
                log.info("Sightengine text response status: %s", resp.status)
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("Sightengine text error status=%s body=%s", resp.status, body[:200])
                    return False, {"reason": "api_error", "status": resp.status}

                result = await resp.json()
                log.info("Sightengine text raw: %s", result)

                # 1) Rules: встроенный словарь брани. profanity = {"matches": [...]}
                profanity = result.get("profanity") or {}
                matches = profanity.get("matches", []) if isinstance(profanity, dict) else []
                if matches:
                    found = [m.get("match") for m in matches if isinstance(m, dict)]
                    log.info("Sightengine profanity matched: %s", found)
                    return True, {"reason": "profanity", "matches": found}

                # 2) ML-классы
                mc = result.get("moderation_classes", {}) or {}
                scores = {
                    k: mc.get(k, 0)
                    for k in ("sexual", "discriminatory", "insulting", "violent", "toxic", "self-harm")
                }
                for category, score in scores.items():
                    try:
                        if float(score) >= TEXT_ML_THRESHOLD:
                            log.info("Sightengine ML blocked: %s=%.3f", category, score)
                            return True, {"reason": f"ml:{category}", "score": score, "scores": scores}
                    except (TypeError, ValueError):
                        continue

                log.info("Sightengine text passed: %s", scores)
                return False, {"reason": "clean", "scores": scores}

    except asyncio.TimeoutError:
        log.warning("Sightengine text timeout")
    except Exception as e:
        log.warning("Sightengine text error: %s", e)

    return False, {"reason": "api_error"}


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
    """AI-проверка изображения. Гарантированно возвращает кортеж."""
    log.info("AI check started. Provider=%s", NSFW_API_PROVIDER)
    if NSFW_API_PROVIDER == "sightengine":
        res = await _check_sightengine(photo_bytes)
        return res if res else (0.0, 0.0)
    elif NSFW_API_PROVIDER == "deepai":
        score = await _check_deepai(photo_bytes)
        return (score or 0.0), 0.0
    log.warning("No AI provider configured")
    return 0.0, 0.0


async def _heuristic_check(
    photo_bytes: bytes,
    caption: Optional[str] = None,
) -> tuple[bool, str]:
    """Быстрая эвристика без внешних API."""
    log.info("Heuristic check started. Photo size=%d bytes", len(photo_bytes))

    img_hash = _compute_hash(photo_bytes)
    log.info("Computed hash: %s", img_hash)
    if img_hash in _banned_hashes:
        log.info("Hash match found in banned list!")
        return True, "hash_match"

    if caption:
        banned_words = {"xxx", "porn", "nude", "naked", "sex", "18+", "onlyfans", "nsfw", "adult"}
        caption_lower = caption.lower()
        for word in banned_words:
            if word in caption_lower:
                log.info("Banned word found in caption: %s", word)
                return True, f"caption_banned_word:{word}"

    log.info("Heuristic check passed")
    return False, ""


async def check_photo(
    bot: Bot,
    message: Message,
    photo: Optional[PhotoSize] = None,
) -> tuple[bool, dict]:
    """Проверяет фото на NSFW-контент."""
    log.info("=== check_photo START for user %d ===", message.from_user.id)

    if photo is None and message.photo:
        photo = message.photo[-1]

    if not photo:
        log.warning("No photo found in message")
        return False, {"reason": "no_photo"}

    try:
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
        log.info("Photo downloaded: %d bytes", len(photo_bytes))
    except Exception as e:
        log.warning("Failed to download photo for NSFW check: %s", e)
        return False, {"reason": "download_error"}

    is_nsfw, reason = await _heuristic_check(photo_bytes, message.caption)
    if is_nsfw:
        log.info("Heuristic check BLOCKED photo")
        await _take_action(message, reason, photo_bytes)
        return True, {"reason": reason, "action": "blocked"}

    nsfw_score, violence_score = await _ai_check(photo_bytes)
    details = {
        "ai_nsfw_score": round(nsfw_score, 3),
        "ai_violence_score": round(violence_score, 3),
    }
    log.info("AI scores: nudity=%.3f, violence=%.3f, threshold_nudity=%.2f, threshold_violence=%.2f",
             nsfw_score, violence_score, NSFWThreshold.NUDITY, NSFWThreshold.VIOLENCE)

    if nsfw_score >= NSFWThreshold.NUDITY or violence_score >= NSFWThreshold.VIOLENCE:
        log.info("AI check BLOCKED photo (score above threshold)")
        await _take_action(message, f"ai_score:{nsfw_score:.2f}", photo_bytes)
        details["action"] = "blocked"
        return True, details

    if nsfw_score >= NSFWThreshold.SUSPICIOUS:
        log.info("Photo flagged as suspicious (score=%.3f)", nsfw_score)
        await _log_suspicious(message, nsfw_score, photo_bytes)
        details["action"] = "flagged_for_review"
    else:
        log.info("Photo passed all checks")
        details["action"] = "passed"

    return False, details


async def _take_action(message: Message, reason: str, photo_bytes: bytes) -> None:
    """Блокирует контент и наказывает пользователя."""
    tg_id = message.from_user.id
    log.info("Taking action against user %d, reason=%s", tg_id, reason)

    try:
        await message.delete()
    except Exception as e:
        log.debug("Could not delete NSFW message: %s", e)

    try:
        await safe_send(message.answer(Msg.NSFW_BLOCKED), log_prefix="nsfw_notify")
    except Exception:
        pass

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

    try:
        async with db() as conn:
            await conn.execute(
                "UPDATE users SET nsfw_strikes = COALESCE(nsfw_strikes, 0) + 1 WHERE tg_id = ?",
                (tg_id,),
            )
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


async def moderate_photo_message(bot: Bot, message: Message) -> bool:
    """Хендлер-обёртка: проверяет фото в сообщении."""
    log.info("moderate_photo_message called for user %d", message.from_user.id)
    if not message.photo:
        return False
    blocked, details = await check_photo(bot, message)
    log.info("NSFW %s for user %d: %s", "blocked" if blocked else "passed",
             message.from_user.id, details)
    return blocked


async def moderate_profile_photo(bot: Bot, tg_id: int, photo_file_id: str) -> tuple[bool, str]:
    """Проверяет фото анкеты. Returns: (is_allowed, reason). Без strikes/ban."""
    log.info("moderate_profile_photo called for user %d", tg_id)
    try:
        file = await bot.get_file(photo_file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
        log.info("Profile photo downloaded: %d bytes", len(photo_bytes))
    except Exception as e:
        log.warning("Failed to download profile photo: %s", e)
        return True, ""

    is_nsfw, reason = await _heuristic_check(photo_bytes)
    if is_nsfw:
        log.info("Profile photo blocked by heuristic: %s", reason)
        img_hash = _compute_hash(photo_bytes)
        _banned_hashes.add(img_hash)
        try:
            async with db() as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO nsfw_banned_hashes (image_hash, reason, created_at) VALUES (?, ?, ?)",
                    (img_hash, reason, int(asyncio.get_event_loop().time())),
                )
        except Exception:
            pass
        return False, reason

    nsfw_score, violence_score = await _ai_check(photo_bytes)
    if nsfw_score >= NSFWThreshold.NUDITY or violence_score >= NSFWThreshold.VIOLENCE:
        log.info("Profile photo blocked by AI: nudity=%.3f violence=%.3f", nsfw_score, violence_score)
        img_hash = _compute_hash(photo_bytes)
        _banned_hashes.add(img_hash)
        try:
            async with db() as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO nsfw_banned_hashes (image_hash, reason, created_at) VALUES (?, ?, ?)",
                    (img_hash, f"ai_nsfw:{nsfw_score:.2f}", int(asyncio.get_event_loop().time())),
                )
        except Exception:
            pass
        return False, f"ai_nsfw:{nsfw_score:.2f}"

    log.info("Profile photo passed checks")
    return True, ""
