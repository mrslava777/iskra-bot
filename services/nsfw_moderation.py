"""NSFW-модерация контента — автоматическая + ручная.

Уровни модерации:
 1. Эвристика: метаданные, подписи, хеши известных изображений
 2. AI-сканер: Sightengine / DeepAI (опционально)
 3. Пользовательские репорты: агрегация жалоб
 4. Ручная модерация админами

FIX v12: _check_sightengine / _check_sightengine_text были перепутаны местами.
FIX v13: переписан скоринг фото под nudity-2.1. Теперь учитываются классы
 раздетости (visibly_undressed, lingerie, male_underwear, nudity_art, sextoy)
 и общий сигнал none. Голые/раздетые фото больше не проскакивают.
 Пляжные bikini/swimwear/cleavage остаются разрешёнными.
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
    """Вычисляет итоговый nudity-score из ответа Sightengine nudity-2.1.

    Логика для дейтинг-приложения:
      - Явный контент (секс/эротика) → жёсткий сигнал.
      - Раздетость (нижнее бельё, обнажёнка, арт-ню, секс-игрушки) → блок.
      - very_suggestive → сильный сигнал.
      - Пляжные bikini / swimwear / cleavage → НЕ блокируем (норм для анкет).
      - Дополнительно: если none очень низкий, а bikini/swimwear при этом
        низкие, значит на фото раздетость → поднимаем скор.
    """
    sc = nudity.get("suggestive_classes", {}) or {}

    explicit = max(
        nudity.get("sexual_activity", 0.0),
        nudity.get("sexual_display", 0.0),
        nudity.get("erotica", 0.0),
        nudity.get("raw", 0.0),  # nudity-2.1: полная обнажёнка
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

    # «Разрешённая» одежда: если фото уверенно пляжное/декольте, это не ню.
    allowed = max(
        sc.get("bikini", 0.0),
        sc.get("swimwear_one_piece", 0.0),
        sc.get("swimwear_male", 0.0),
        sc.get("cleavage", 0.0),
        sc.get("miniskirt", 0.0),
        sc.get("minishort", 0.0),
    )

    # none = вероятность, что обнажёнки НЕТ вовсе. Если она низкая, а при этом
    # это не «разрешённая» одежда — значит на фото раздетость, которую модель
    # не разложила по явным классам. Подтягиваем скор.
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
        log.info("Sightengine credentials: user=%s... secret=%s...",
                 api_user[:5], api_secret[:5])
    except ValueError as e:
        log.error("Failed to parse NSFW_API_KEY (expected user:secret): %s", e)
        return 0.0, 0.0

    import aiohttp

    data = aiohttp.FormData()
    data.add_field("media", io.BytesIO(photo_bytes), filename="photo.jpg")
    data.add_field("api_user", api_user)
    data.add_field("api_secret", api_secret)
    data.add_field("models", "nudity-2.1,weapon,violence,offensive")

    log.info("Sending request to Sightengine API...")
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
    """Sightengine Text Moderation API.

    Returns: (is_blocked, details)
    """
    if not NSFW_API_KEY or not NSFW_API_PROVIDER:
        return False, {"reason": "no_api_config"}

    try:
        api_user, api_secret = NSFW_API_KEY.split(":", 1)
    except ValueError:
        log.error("Failed to parse NSFW_API_KEY (expected user:secret)")
        return False, {"reason": "bad_api_key_format"}

    import aiohttp

    data = {
        "text": text,
        "lang": "ru,en",
        "mode": "ml,rules",
        "models": "general,self-harm",
        "categories": "profanity,personal,link,drug,weapon,violence,self-harm,medical,extremism,spam,content-trade,money-transaction",
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
                if resp.status == 200:
                    result = await resp.json()
                    log.info("Sightengine text raw: %s", result)

                    details = {
                        "sexual": result.get("moderation_classes", {}).get("sexual", 0),
                        "toxic": result.get("moderation_classes", {}).get("toxic", 0),
                        "insulting": result.get("moderation_classes", {}).get("insulting", 0),
                        "violent": result.get("moderation_classes", {}).get("violent", 0),
                        "discriminatory": result.get("moderation_classes", {}).get("discriminatory", 0),
                        "self_harm": result.get("moderation_classes", {}).get("self-harm", 0),
                    }

                    profanity = result.get("profanity", [])
                    if profanity:
                        details["profanity_found"] = profanity
                        log.info("Sightengine found profanity: %s", profanity)
                        return True, details

                    threshold = 0.5
                    for category, score in details.items():
                        if score >= threshold:
                            log.info("Sightengine ML blocked: %s=%.3f", category, score)
                            return True, details

                    log.info("Sightengine text passed")
                    return False, details
                else:
                    body = await resp.text()
                    log.warning("Sightengine text error status=%s body=%s", resp.status, body[:200])
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
    """Запускает AI-проверку. Возвращает (nsfw_score, violence_score).

    Гарантированно возвращает кортеж, даже если провайдер вернул None.
    """
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
        log.info("Downloading photo file_id=%s", photo.file_id)
        file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
        log.info("Photo downloaded: %d bytes", len(photo_bytes))
    except Exception as e:
        log.warning("Failed to download photo for NSFW check: %s", e)
        return False, {"reason": "download_error"}

    log.info("Running heuristic check...")
    is_nsfw, reason = await _heuristic_check(photo_bytes, message.caption)
    if is_nsfw:
        log.info("Heuristic check BLOCKED photo")
        await _take_action(message, reason, photo_bytes)
        return True, {"reason": reason, "action": "blocked"}

    log.info("Running AI check...")
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
        log.info("Message deleted")
    except Exception as e:
        log.debug("Could not delete NSFW message: %s", e)

    try:
        await safe_send(
            message.answer(Msg.NSFW_BLOCKED),
            log_prefix="nsfw_notify",
        )
        log.info("User notified")
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
        log.info("Hash saved to banned list")
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
        log.info("Logged suspicious content for review")
    except Exception as e:
        log.debug("Failed to log suspicious content: %s", e)


async def moderate_photo_message(bot: Bot, message: Message) -> bool:
    """Хендлер-обёртка: проверяет фото в сообщении."""
    log.info("moderate_photo_message called for user %d", message.from_user.id)
    if not message.photo:
        log.info("No photo in message, skipping")
        return False
    blocked, details = await check_photo(bot, message)
    if blocked:
        log.info("NSFW blocked from user %d: %s", message.from_user.id, details)
    else:
        log.info("NSFW passed for user %d: %s", message.from_user.id, details)
    return blocked


async def moderate_profile_photo(bot: Bot, tg_id: int, photo_file_id: str) -> tuple[bool, str]:
    """Проверяет фото анкеты перед сохранением. Returns: (is_allowed, reason).

    Не вызывает _take_action — нет auto-ban/strikes для фото профиля.
    """
    log.info("moderate_profile_photo called for user %d", tg_id)
    try:
        file = await bot.get_file(photo_file_id)
        photo_bytes = await bot.download_file(file.file_path)
        photo_bytes = photo_bytes.read() if hasattr(photo_bytes, "read") else photo_bytes
        log.info("Profile photo downloaded: %d bytes", len(photo_bytes))
    except Exception as e:
        log.warning("Failed to download profile photo: %s", e)
        return True, ""  # fallback: разрешаем если не смогли проверить

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
