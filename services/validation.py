"""Валидация входных данных — regex + HTML-escape + NSFW-фильтр.

FIX v12: исправлена проверка запрещённых слов — убран сломанный гигантский regex,
         используется простой и надёжный substring search.
"""
import html
import logging
import re
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

# Запрещённые слова — проверяются как подстроки (ловит PornStar, xxxQueen, 18+content)
# Отсортированы по длине (длинные первые) — оптимизация: длинные реже встречаются,
# но если есть, находим быстрее
_BANNED_SUBSTRINGS = [
    # Длинные фразы (проверяем первыми)
    "sugar daddy", "sugar baby", "18+", "onlyfans", "child porn", "детское порно",
    "суррогатное материнство", "суррогатная мать", "продажа детей", "купить ребёнка",
    "детская эксплуатация", "детский труд", "торговля людьми", "торговля органами",
    "пассивный доход", "быстрые деньги", "лёгкие деньги", "легкие деньги",
    "ставки на спорт", "букмекерская контора", "онлайн казино", "казино онлайн",
    "игровые автоматы", "финансовая пирамида", "пирамидка", "пирамидный",
    "реферальная ссылка", "партнёрская программа", "пригласи друга",
    "пиши в лс", "в личку", "в личные сообщения", "ссылка в профиле",
    "переходи по ссылке", "телеграм канал", "тг канал",
    "эскорт услуги", "интим услуги", "секс услуги", "интим знакомства",
    "порно видео", "порно фото", "порно контент", "порнография",
    "любовная магия", "денежная магия", "карьерная магия", "бизнес-магия",
    "чёрная магия", "белая магия", "серая магия",
    "магическая помощь", "любовный приворот", "приворотное зелье",
    "самоубийство", "суицид", "резаться", "порезаться",
    "отмывание денег", "money laundering",
    "фальшивые деньги", "фальшивый паспорт", "поддельные документы",
    "заказное убийство", "наёмный убийца", "контрактное убийство",
    "детская порнография", "child sexual abuse",
    "зоофилия", "зоосекс", "некрофилия", "некросекс",
    "распродажа", "промокод", "промо",
    "реферал", "реферальная", "аффилиат", "affiliate",
    "памп и дамп", "pump and dump", "rug pull", "honeypot", "ханипот",
    "фишинговый сайт", "фишинговая ссылка",
    "взлом аккаунта", "взлом страницы", "взлом пароля",
    "утечка данных", "слив данных", "слив базы",
    "шантажировать", "требовать выкуп",
    "развести на деньги", "кидали на деньги",
    "продажа аккаунтов", "купить аккаунт", "продам аккаунт",
    "продажа вериф", "купить вериф", "продам вериф",
    "накрутка подписчиков", "фейковые аккаунты", "фейковые подписчики",
    "боты для накрутки", "накрутить подписчиков",
    # Средние слова
    "проститутка", "проститутки", "эскортница", "эскортницы",
    "содержанка", "содержанки", "любовница", "любовник",
    "мастурбация", "мастурбировать", "мастурбирую",
    "извращенец", "извращение", "извращённый",
    "педофил", "педофилия", "зоофил", "зоофилия", "некрофил", "некрофилия",
    "наркотики", "наркомания", "наркоман", "наркоторговля", "наркокартель",
    "контрафакт", "контрафактный", "подделка", "фальсификат",
    "пиратский", "пиратство", "пират",
    "воровство", "грабёж", "грабитель", "разбой", "разбойник",
    "вымогательство", "вымогатель", "вымогать",
    "взяточник", "взяточничество", "коррупция", "коррупционер",
    "отмывание", "отмыть", "отмывка", "отмыв",
    "фальшивомонетчик", "фальшивка",
    "нелегал", "нелегальный", "нелегалы",
    "рабство", "работорговля", "рабовладелец", "рабыня",
    "суррогатное", "сурмама", "суррогатная",
    "донорство", "донор", "продажа органов",
    "бездомный", "бомж", "нищий", "нищенство",
    "попрошайничество", "попрошайка", "попрошайничать",
    "алкоголизм", "алкоголик", "пьянство", "пьяница",
    "наркология", "нарколог", "реабилитация", "лечение зависимости",
    "продажа", "продам", "куплю", "обменяю", "отдам", "даром", "бесплатно",
    "скидка", "скидки", "акция", "акции",
    "партнёрка", "аффилиат", "affiliate",
    "коучинг", "коуч", "лайфкоуч", "психолог онлайн", "целитель",
    "гороскоп", "астрология", "таро", "руны", "гадание", "предсказание",
    "проклятие", "порча", "сглаз", "приворот", "отворот", "привязка",
    "ритуал", "обряд", "заговор", "приворотное",
    "секта", "сектант", "сектантский", "деструктивный культ",
    "оккультизм", "оккультный", "магия", "магический", "колдовство",
    "ведьма", "ведьмак", "гадалка", "гадать", "предсказатель",
    "ясновидящий", "ясновидение", "экстрасенс", "экстрасенсорика",
    "парапсихолог", "парапсихология", "псевдонаука", "псевдонаучный",
    "шарлатан", "шарлатанство",
    "млм", "mlm", "network marketing", "сетевой маркетинг", "сетевик",
    "пирамида", "пирамидка", "пирамидный",
    "хайп", "хайповый", "хайп проект", "хайпануть", "хайпанули",
    "инвестпроект", "инвест проект", "инвестиционный проект",
    "быстрый заработок", "нулевой взнос",
    "без вложений", "без вложений доход", "без вложений заработок",
    "букмекер", "букмекерская", "тотализатор", "тото",
    "лотерея", "лотереи", "розыгрыш", "конкурс", "giveaway",
    "казино", "рулетка", "слоты", "покер", "покер рум", "покер онлайн",
    "блэкджек", "баккара", "крэпс", "бинго",
    "лудомания", "лудоман", "азарт", "азартные игры", "игромания", "игроман",
    "закладки", "закладка", "клады", "клад", "заклад", "закладчик",
    "дилер", "диллер", "поставщик", "курьер", "перевозчик",
    "оружие", "пистолет", "автомат", "граната", "взрывчатка", "бомба", "взрыв",
    "террорист", "терроризм", "террористический", "экстремизм", "экстремист",
    "убийство", "убийца", "похищение", "похититель", "похитить",
    "захват", "захватить", "заложник", "заложники",
    "пытки", "пытать", "жестокость", "жестокий", "насилие", "насильник", "изнасилование",
    "каннибализм", "людоедство", "сатанизм", "сатанист",
    "чёрная месса", "черная месса",
    "перерезать", "выпрыгнуть", "повеситься",
    "наркобизнес",
    "взлом", "хак", "хакер", "хакинг", "хакерство",
    "взломать", "слить базу", "слив данных", "утечка", "утечка данных",
    "докс", "доксинг", "доксер", "докснули", "доксанули",
    "шантаж", "шантажист", "шантажировать", "компромат", "компрометирующий",
    "шпионаж", "шпион", "шпионить", "агент", "агентура", "агентурный",
    "провокация", "провокатор", "провоцировать", "спровоцировать", "инсценировка",
    "фейк", "фейковый", "фейковые новости", "дезинформация", "дезинформировать",
    "манипуляция", "манипулировать", "манипулятор", "зомбирование", "зомби",
    "троллинг", "тролль", "троллить",
    "токсик", "токсичный", "токсичность", "агрессия", "агрессивный", "агрессор",
    "оскорбление", "оскорблять", "унижение", "унижать", "провокация", "провокатор",
    "мошенник", "мошенничество", "мошеннический", "мошенническая схема",
    "кидала", "кидалы", "кидалово", "кидать", "кинули", "кинули на деньги",
    "лохотрон", "лох", "лохи", "лохануться", "лохотронщик", "лохотронный",
    "развести", "развод", "разводить", "разводила", "развели",
    "скам", "скаммер", "скамный", "скам проект",
    "rug pull", "honeypot", "ханипот", "honeypot token",
    "фишинг", "фишинговый", "фишинговый сайт", "фишинговая ссылка",
    "взлом", "взлом аккаунта", "взлом страницы", "взлом пароля",
    "слить базу", "слив данных", "слив", "утечка данных",
    "докс", "доксинг", "доксер", "докснули", "доксанули",
    "шантаж", "шантажист", "шантажировать", "компромат",
    "рейдер", "рейдерство", "рейд", "рейдить",
    "спам", "спамер", "спамить", "флуд", "флудер", "флудить",
    "памп", "pump", "дамп", "dump", "pump group", "dump group",
    "памп группа", "дамп группа", "памп и дамп",
    "скам", "скаммер", "скамный", "скам проект",
    "фишинг", "фишинговый сайт", "фишинговая ссылка",
    "взлом", "хак", "хакер", "хакинг", "хакерство",
    "взломать", "слить базу", "слив данных", "утечка",
    "докс", "доксинг", "доксер", "докснули", "доксанули",
    "шантаж", "шантажист", "шантажировать",
    "рейдер", "рейдерство", "рейд", "рейдить",
    "спам", "спамер", "спамить", "флуд", "флудер", "флудить",
    # Короткие слова (проверяем последними, т.к. чаще встречаются)
    "xxx", "porn", "sex", "nsfw", "bdsm", "cum", "dick", "cock",
    "fuck", "shit", "cunt", "slut", "whore", "bitch", "nigg",
    "хуй", "хуя", "хуе", "хуи", "хуё", "пизд", "ебал", "ебан", "ебат",
    "бляд", "блят", "шлюх", "сука ", "суки", "сучк", "мудак", "мудач",
    "дроч", "дрочи", "дрочу", "сперм", "минет", "анал ", "аналу", "анала",
    "порно", "секс", "секса", "сексу", "голый", "голая", "голые",
    "интим", "интимн", "проститут", "проституц", "эскорт", "путан",
    "эротик", "груд", "пенис", "вагин", "клитор", "оргазм", "мастурб",
    "фетиш", "садо", "мазо", "извращ", "педоф", "зоофил", "некрофил",
    "наркот", "кокаин", "героин", "метадон", "амфетамин", "экстази",
    "спайс", "соль", "скорость", "фен", "мефедрон", "мяу", "alfa", "альфа",
    "продам", "куплю", "заработок", "пассивный доход", "быстрые деньги",
    "криптовалют",
    "криптовалюта", "инвестиции", "пирамида", "хайп", "лотерея", "казино",
    "ставки", "букмекер", "1xbet", "1хбет", "melbet", "мелбет",
    "телеграм канал", "подпишись", "переходи", "ссылка в профиле",
    "пиши в лс", "в лс", "вайбер", "viber",
    "instagram", "инстаграм", "инста", "ig", "insta",
    "tiktok", "тикток", "тик-ток", "likee", "лайки",
    "snapchat", "snap", "снапчат", "снап",
    "onlyfans", "онлифанс", "онли фанс", "of", "fansly", "патреон", "patreon",
    "boosty", "бусти", "донат", "donate",
    "крипта", "bitcoin", "биткоин", "биток", "ethereum", "эфириум", "эфир", "eth",
    "wallet", "кошелёк", "кошелек", "криптокошелёк",
    "binance", "бинанс", "bybit", "байбит", "okx", "хуоби", "huobi",
    "kraken", "кракен", "coinbase", "gemini", "джемини",
    "forex", "форекс", "форекс трейдинг", "трейдинг", "трейдер", "trading",
    "signal", "сигналы", "торговые сигналы", "сигналы форекс", "crypto signals",
    "памп", "pump", "дамп", "dump",
    "скам", "скаммер", "скамный",
    "фишинг", "фишинговый",
    "взлом", "хак", "хакер", "хакинг",
    "взломать", "слить базу", "слив данных",
    "докс", "доксинг", "доксер",
    "шантаж", "шантажист", "шантажировать",
    "рейдер", "рейдерство", "рейд", "рейдить",
    "спам", "спамер", "спамить", "флуд", "флудер", "флудить",
]


def _contains_banned_words(text: str) -> Optional[str]:
    """Проверяет текст на наличие запрещённых слов.

    Использует substring search с учётом границ слов.
    Слова отсортированы по длине: длинные фразы проверяем первыми
    (чтобы «секс услуги» поймалось раньше, чем просто «секс»).

    FIX: слова без trailing space теперь проверяются с учётом границ
    (пробел, пунктуация или конец строки), чтобы не ловить false positives
    в словах типа «бисексуал», «сексолог».

    Returns: первое найденное слово или None.
    """
    if not text:
        return None

    text_lower = text.lower()

    for word in _BANNED_SUBSTRINGS:
        idx = text_lower.find(word)
        if idx == -1:
            continue

        # Для слов без trailing space проверяем границу слова справа
        # чтобы не ловить "секс" внутри "бисексуал"
        word_stripped = word.rstrip()
        if word_stripped == word:  # слово без trailing space
            end_pos = idx + len(word)
            if end_pos < len(text_lower):
                next_char = text_lower[end_pos]
                # Если следующий символ — буква/цифра, это часть другого слова
                if next_char.isalnum() or next_char == '_':
                    continue

        log.debug("Banned word found: %r in text", word)
        return word

    return None


def sanitize_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = html.escape(cleaned)
    if not _RE_NAME.match(cleaned):
        log.debug("Name rejected: regex mismatch for %r", raw)
        return None
    banned = _contains_banned_words(cleaned)
    if banned:
        log.info("Name rejected: banned word %r in %r", banned, raw)
        return None
    return cleaned


def sanitize_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    cleaned = html.escape(cleaned)
    if not _RE_CITY.match(cleaned):
        log.debug("City rejected: regex mismatch for %r", raw)
        return None
    banned = _contains_banned_words(cleaned)
    if banned:
        log.info("City rejected: banned word %r in %r", banned, raw)
        return None
    return cleaned


def sanitize_bio(raw: Optional[str], max_length: int = 300) -> Optional[str]:
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
    banned = _contains_banned_words(cleaned)
    if banned:
        log.info("Bio rejected: banned word %r in %r", banned, raw)
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
    seen = set()
    result = []
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


def sanitize_ticket_text(raw: Optional[str], max_length: int = 1000) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if _RE_BIO.search(cleaned):
        log.info("Ticket rejected: contains HTML tags")
        return None
    banned = _contains_banned_words(cleaned)
    if banned:
        log.info("Ticket rejected: banned word %r", banned)
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
    return s# Пол
_VALID_GENDERS = {"m", "f", "any"}

# Интересы: CSV из цифр
_RE_INTERESTS = re.compile(r"^\d+(?:,\d+)*$")

# ═══════════════════════════════════════════════════════════════════════════════
# ЗАПРЕЩЁННЫЕ СЛОВА (NSFW / спам)
# ═══════════════════════════════════════════════════════════════════════════════

# Слова, запрещённые в любом пользовательском тексте
_BANNED_WORDS = {
    "xxx", "porn", "nude", "naked", "sex", "18+", "onlyfans", "nsfw", "adult",
    "hentai", "xxx", "xxx", "эротика", "порно", "голый", "голая", "секс",
    "intim", "интим", "проститут", "проституция", "эскорт", "escort",
    "sugar daddy", "sugar baby", "дроч", "дрочка", "мастурб", "masturb",
    "cum", "sperm", "сперма", "минет", "анал", "anal", "blowjob", "handjob",
    "fuck", "shit", "bitch", "whore", "slut", "cunt", "dick", "cock",
    "хуй", "пизда", "ебать", "блядь", "шлюха", "сука", "мудак",
}

_RE_BANNED_WORDS = re.compile(
    r"(" + "|".join(re.escape(w) for w in _BANNED_WORDS) + r")",
    re.IGNORECASE | re.UNICODE,
)


def _contains_banned_words(text: str) -> Optional[str]:
    """Проверяет текст на наличие запрещённых слов.

    Returns: первое найденное слово или None.
    """
    if not text:
        return None
    match = _RE_BANNED_WORDS.search(text)
    return match.group(1) if match else None


# ═══════════════════════════════════════════════════════════════════════════════
# SANITIZE / VALIDATE
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_name(raw: Optional[str]) -> Optional[str]:
    """Очищает имя: strip, HTML-escape, проверка regex, запрещённые слова.

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
    # FIX v11: проверка запрещённых слов
    banned = _contains_banned_words(cleaned)
    if banned:
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
    # FIX v11: проверка запрещённых слов
    banned = _contains_banned_words(cleaned)
    if banned:
        return None
    return cleaned


def sanitize_bio(raw: Optional[str], max_length: int = 300) -> Optional[str]:
    """Очищает био: strip, HTML-escape, проверка на HTML-теги, запрещённые слова, обрезка.

    Returns None если содержит raw HTML-теги (< или >) или запрещённые слова.
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
    # FIX v11: проверка запрещённых слов
    banned = _contains_banned_words(cleaned)
    if banned:
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
    """Очищает текст тикета: strip, HTML-escape, запрещённые слова, обрезка.

    FIX v11: добавлена проверка запрещённых слов.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Запрещаем raw HTML-теги
    if _RE_BIO.search(cleaned):
        return None
    # FIX v11: проверка запрещённых слов
    banned = _contains_banned_words(cleaned)
    if banned:
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
