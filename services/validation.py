"""Валидация входных данных — regex + HTML-escape + NSFW-фильтр.

FIX v13: модерация текста переведена на Sightengine Text Moderation API
 (ML general/self-harm + встроенный профанити-словарь, lang=ru,en) как
 ОСНОВНОЙ фильтр. Локальный список ужат до компактной офлайн-подстраховки
 с антиобфускацией (раскладка, повторы, разделители между буквами).

 Логика sanitize_*:
   1) regex-валидация формата;
   2) локальный быстрый фильтр (мгновенно ловит явное, работает без сети);
   3) Sightengine Text API — основной семантический модератор.
      Если API недоступен, полагаемся на п.2.
"""
import html
import logging
import re
import unicodedata
from typing import Optional

log = logging.getLogger("iskra.validation")

_RE_NAME = re.compile(r"^[\w\s\-]{2,32}$", re.UNICODE)
_RE_CITY = re.compile(r"^[\w\s\-\.]{1,48}$", re.UNICODE)
_RE_BIO = re.compile(r"[<>]", re.UNICODE)
_RE_USERNAME = re.compile(r"^[a-zA-Z0-9_]{5,32}$")
_RE_USER_ID = re.compile(r"^\d+$")
_RE_CALLBACK = re.compile(r"^[\w\-:]{1,64}$")
_VALID_TICKET_CATEGORIES = {"report", "rights", "other"}
_VALID_GENDERS = {"m", "f", "any"}
_RE_INTERESTS = re.compile(r"^\d+(?:,\d+)*$")

# ═══════════════════════════════════════════════════════════════════════════════
# АНТИОБФУСКАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════
# Латиница/цифры → кириллица (ловит "cyка", "6лядь", "xyй", "$ука")
_LOOKALIKE = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х",
    "k": "к", "m": "м", "t": "т", "h": "н", "b": "в", "n": "п", "u": "и",
    "3": "з", "0": "о", "4": "ч", "6": "б", "9": "д", "@": "а", "$": "с",
})


def _normalize_for_moderation(text: str) -> str:
    """Схлопывает обфускацию: раскладку, разделители между буквами, повторы."""
    t = unicodedata.normalize("NFKC", text).lower().translate(_LOOKALIKE)
    t = "".join(ch for ch in t if ch.isalnum())  # убираем пробелы/точки/дефисы
    # схлопываем повторы: "бляяядь" -> "блядь"
    dedup, prev = [], ""
    for ch in t:
        if ch != prev:
            dedup.append(ch)
        prev = ch
    return "".join(dedup)


# ═══════════════════════════════════════════════════════════════════════════════
# КОМПАКТНЫЙ ОФЛАЙН-СЛОВАРЬ (подстраховка на случай недоступности Sightengine)
# ═══════════════════════════════════════════════════════════════════════════════
# Основную ширину покрытия обеспечивает Sightengine. Здесь — только «ядро»:
# самое злостное, что нельзя пропускать даже при сбое API.
_BANNED_SUBSTRINGS = [
    # Многословные фразы (проверяются по исходному тексту)
    "детское порно", "детская порнография", "child porn", "child sexual abuse",
    "интим услуги", "секс услуги", "эскорт услуги", "интим знакомства",
    "заказное убийство", "наёмный убийца",
    # Мат (корни, ловятся по нормализованному тексту, в т.ч. в склейках)
    "хуй", "хуе", "хуя", "хуё", "хуи", "ебать", "ебан", "ебал", "ебуч", "ебош",
    "ебаш", "наебн", "выебн", "уебищ", "уебок", "пизд", "бляд", "блят", "блядь",
    "сука", "суки", "сучар", "сученыш", "мудак", "мудач", "мудил", "мудозвон",
    "шлюх", "шлюхин", "гандон", "гондон", "дрочи", "дрочу", "дрочер", "дрочил",
    "манда", "мандав", "пидор", "пидар", "педик", "гнида", "залуп", "мразь",
    "хуесос", "хуеплет", "долбоеб", "долбаеб", "чмо", "выблядок",
    "сперм", "минет", "куннилингус", "анилингус",
    # Порно/контент
    "порно", "порнуха", "porn", "xxx", "nsfw", "bdsm", "onlyfans", "онлифанс",
    "нюдс", "nudes", "интимн", "проститу", "порнограф", "эротик",
    # Наркотики (ядро)
    "наркот", "кокаин", "героин", "амфетамин", "мефедрон", "экстази", "спайс",
    # Английский мат
    "fuck", "cunt", "nigger", "whore", "slut", "dickhead", "motherfuck",
]

# Короткие/неоднозначные корни — только как отдельное слово в ИСХОДНОМ тексте,
# чтобы не ловить "секс" в "бисексуал", "анал" в "аналог", "клад" в "укладка".
_BOUNDARY_ONLY = {"секс", "анал", "клад", "фен", "соль", "мяу", "sex", "of", "ig"}


def _contains_banned_words(text: str) -> Optional[str]:
    """Офлайн-фильтр запрещённых слов с антиобфускацией.

    Одиночные корни ищутся по нормализованному тексту (ловит склейки и
    подмену символов), фразы с пробелами — по исходному, короткие
    неоднозначные корни (_BOUNDARY_ONLY) — только по границе слова.
    Returns: найденное слово или None.
    """
    if not text:
        return None

    original = text.lower()
    normalized = _normalize_for_moderation(text)

    for raw in _BANNED_SUBSTRINGS:
        w = raw.strip().lower()
        if not w:
            continue

        if w in _BOUNDARY_ONLY:
            idx = original.find(w)
            while idx != -1:
                left_ok = idx == 0 or not original[idx - 1].isalnum()
                end = idx + len(w)
                right_ok = end >= len(original) or not original[end].isalnum()
                if left_ok and right_ok:
                    log.info("Banned word (boundary): %r", w)
                    return w
                idx = original.find(w, idx + 1)
            continue

        if " " in w:
            if w in original:
                log.debug("Banned phrase: %r", w)
                return w
        else:
            needle = _normalize_for_moderation(w)
            if needle and needle in normalized:
                log.debug("Banned word: %r", w)
                return w

    return None


async def _check_text_with_sightengine(text: str) -> tuple[bool, Optional[dict]]:
    """Основная модерация текста через Sightengine Text API.

    Returns: (is_blocked, details_or_None). При сбое API — (False, None),
    тогда полагаемся на локальный офлайн-фильтр.
    """
    try:
        from services.nsfw_moderation import _check_sightengine_text
        blocked, details = await _check_sightengine_text(text)
        return blocked, details
    except Exception as e:
        log.debug("Sightengine text check failed: %s", e)
        return False, None


async def _moderate_text(cleaned: str, label: str) -> bool:
    """Единый пайплайн модерации текста. Returns True если текст ЗАПРЕЩЁН.

    1) локальный офлайн-фильтр (быстрый, без сети);
    2) Sightengine Text API (основной семантический модератор).
    """
    banned = _contains_banned_words(cleaned)
    if banned:
        log.info("%s rejected (local): %r", label, banned)
        return True

    try:
        blocked, details = await _check_text_with_sightengine(cleaned)
        if blocked:
            log.info("%s rejected (Sightengine): %s", label, details)
            return True
    except Exception:
        pass  # API опционален — не роняем валидацию при недоступности

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ПУБЛИЧНЫЕ САНИТАЙЗЕРЫ
# ═══════════════════════════════════════════════════════════════════════════════

async def sanitize_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = html.escape(cleaned)
    if not _RE_NAME.match(cleaned):
        log.debug("Name rejected: regex mismatch for %r", raw)
        return None
    if await _moderate_text(cleaned, "Name"):
        return None
    return cleaned


async def sanitize_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = html.escape(cleaned)
    if not _RE_CITY.match(cleaned):
        log.debug("City rejected: regex mismatch for %r", raw)
        return None
    if await _moderate_text(cleaned, "City"):
        return None
    return cleaned


async def sanitize_bio(raw: Optional[str], max_length: int = 300) -> Optional[str]:
    if not raw:
        return None
    if raw.strip() == "-":
        return ""
    cleaned = raw.strip()
    if not cleaned:
        return None
    if _RE_BIO.search(cleaned):
        log.info("Bio rejected: contains HTML tags in %r", raw)
        return None
    if await _moderate_text(cleaned, "Bio"):
        return None
    cleaned = html.escape(cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def sanitize_username(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().lstrip("@")
    if not cleaned:
        return None
    if not _RE_USERNAME.match(cleaned):
        return None
    return cleaned


def validate_age(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        age = int(raw.strip())
    except (ValueError, TypeError):
        return None
    if 14 <= age <= 99:
        return age
    return None


def validate_user_id(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not _RE_USER_ID.match(cleaned):
        return None
    return int(cleaned)


def validate_callback_data(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned or len(cleaned) > 64:
        return None
    if not _RE_CALLBACK.match(cleaned):
        return None
    return cleaned


def validate_gender(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _VALID_GENDERS:
        return cleaned
    return None


def validate_seeking(raw: Optional[str]) -> Optional[str]:
    return validate_gender(raw)


def validate_interests(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if not _RE_INTERESTS.match(cleaned):
        return None
    parts = [p.strip() for p in cleaned.split(",")]
    seen, result = set(), []
    for p in parts:
        if p not in seen and len(result) < 5:
            seen.add(p)
            result.append(p)
    return ",".join(result)


def validate_ticket_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _VALID_TICKET_CATEGORIES:
        return cleaned
    return None


async def sanitize_ticket_text(raw: Optional[str], max_length: int = 1000) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if _RE_BIO.search(cleaned):
        log.info("Ticket rejected: contains HTML tags")
        return None
    if await _moderate_text(cleaned, "Ticket"):
        return None
    cleaned = html.escape(cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def escape_html(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return html.escape(str(raw))


def truncate(raw: Optional[str], max_length: int) -> str:
    if not raw:
        return ""
    s = str(raw)
    if len(s) > max_length:
        return s[:max_length]
    return s
