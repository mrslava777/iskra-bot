"""Валидация входных данных — regex + HTML-escape.

Все пользовательские строки проходят через sanitize_* перед записью в БД
и отображением в Telegram (HTML parse_mode).
"""
import html
import re
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

# Имя: буквы (включая кириллицу), пробелы, дефисы. 2–32 символа.
_RE_NAME = re.compile(r"^[\w\s\-]{2,32}$", re.UNICODE)

# Город: буквы, цифры, пробелы, дефисы, точки. 1–48 символов.
_RE_CITY = re.compile(r"^[\w\s\-\.]{1,48}$", re.UNICODE)

# Био: любые символы, но без HTML-тегов. Длина проверяется отдельно.
_RE_BIO = re.compile(r"[<>]", re.UNICODE)

# Username Telegram: буквы, цифры, подчёркивания. 5–32 символа.
_RE_USERNAME = re.compile(r"^[a-zA-Z0-9_]{5,32}$")

# ID пользователя: только цифры
_RE_USER_ID = re.compile(r"^\d+$")

# Callback data: только разрешённые символы (предотвращает инъекцию)
_RE_CALLBACK = re.compile(r"^[\w\-:]{1,64}$")

# Категория тикета: только разрешённые ключи
_VALID_TICKET_CATEGORIES = {"report", "rights", "other"}

# Пол
_VALID_GENDERS = {"m", "f", "any"}

# Интересы: CSV из цифр
_RE_INTERESTS = re.compile(r"^\d+(?:,\d+)*$")


# ═══════════════════════════════════════════════════════════════════════════════
# SANITIZE / VALIDATE
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_name(raw: Optional[str]) -> Optional[str]:
    """Очищает имя: strip, HTML-escape, проверка regex.

    Returns None если валидация не пройдена.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # HTML-escape для безопасного отображения в Telegram HTML
    cleaned = html.escape(cleaned)
    if not _RE_NAME.match(cleaned):
        return None
    return cleaned


def sanitize_city(raw: Optional[str]) -> Optional[str]:
    """Очищает название города."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = html.escape(cleaned)
    if not _RE_CITY.match(cleaned):
        return None
    return cleaned


def sanitize_bio(raw: Optional[str], max_length: int = 300) -> Optional[str]:
    """Очищает био: strip, HTML-escape, проверка на HTML-теги, обрезка.

    Returns None если содержит raw HTML-теги (< или >).
    """
    if not raw:
        return None
    if raw.strip() == "-":
        return ""
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Запрещаем raw HTML-теги — они ломают parse_mode=HTML
    if _RE_BIO.search(cleaned):
        return None
    cleaned = html.escape(cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def sanitize_username(raw: Optional[str]) -> Optional[str]:
    """Валидирует Telegram username (без @)."""
    if not raw:
        return None
    cleaned = raw.strip().lstrip("@")
    if not cleaned:
        return None
    if not _RE_USERNAME.match(cleaned):
        return None
    return cleaned


def validate_age(raw: Optional[str]) -> Optional[int]:
    """Валидирует возраст: 14–99."""
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
    """Валидирует ID пользователя (только цифры)."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not _RE_USER_ID.match(cleaned):
        return None
    return int(cleaned)


def validate_callback_data(raw: Optional[str]) -> Optional[str]:
    """Валидирует callback_data: только разрешённые символы."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned or len(cleaned) > 64:
        return None
    if not _RE_CALLBACK.match(cleaned):
        return None
    return cleaned


def validate_gender(raw: Optional[str]) -> Optional[str]:
    """Валидирует пол: m / f / any."""
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _VALID_GENDERS:
        return cleaned
    return None


def validate_seeking(raw: Optional[str]) -> Optional[str]:
    """Валидирует кого ищет: m / f / any."""
    return validate_gender(raw)


def validate_interests(raw: Optional[str]) -> Optional[str]:
    """Валидирует строку интересов: CSV из цифр, макс 5 штук."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if not _RE_INTERESTS.match(cleaned):
        return None
    parts = [p.strip() for p in cleaned.split(",")]
    # Убираем дубликаты и ограничиваем 5
    seen = set()
    result = []
    for p in parts:
        if p not in seen and len(result) < 5:
            seen.add(p)
            result.append(p)
    return ",".join(result)


def validate_ticket_category(raw: Optional[str]) -> Optional[str]:
    """Валидирует категорию тикета."""
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _VALID_TICKET_CATEGORIES:
        return cleaned
    return None


def sanitize_ticket_text(raw: Optional[str], max_length: int = 1000) -> Optional[str]:
    """Очищает текст тикета: strip, HTML-escape, обрезка."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Запрещаем raw HTML-теги
    if _RE_BIO.search(cleaned):
        return None
    cleaned = html.escape(cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def escape_html(raw: Optional[str]) -> str:
    """Безопасный HTML-escape для любой строки.

    Используется перед отправкой пользовательских данных в Telegram с parse_mode=HTML.
    """
    if not raw:
        return ""
    return html.escape(str(raw))


def truncate(raw: Optional[str], max_length: int) -> str:
    """Обрезает строку до max_length символов."""
    if not raw:
        return ""
    s = str(raw)
    if len(s) > max_length:
        return s[:max_length]
    return s
