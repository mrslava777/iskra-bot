"""Константы для бота Искра, все магические числа и строки в одном месте.

Импорт из data.enums намеренно отсутствует, чтобы не создавать циклические зависимости.
"""


class Age:
    """Лимиты возраста."""

    MIN = 14
    MAX = 99


class Length:
    """Максимальные длины полей."""

    NAME = 32
    CITY = 48
    BIO = 300
    TICKET_TEXT = 1000


class Photo:
    """Лимиты фотографий."""

    MAX_TOTAL = 5
    MAX_EXTRA = 4
    MAIN_POSITION = 0


class Interest:
    """Лимиты интересов."""

    MAX_SELECTED = 5
    COLUMNS_PER_ROW = 2


class Profile:
    """Константы профиля."""

    COMPLETE_FIELDS_COUNT = 5
    COMPLETE_THRESHOLD = 4


class BadgeThreshold:
    """Пороги для получения значков."""

    FIRST_MATCH = 1
    TEN_MATCHES = 10
    FIFTY_MATCHES = 50
    FIRST_LIKE = 1
    HUNDRED_LIKES = 100
    STREAK_WEEK = 7
    STREAK_MONTH = 30
    HIGH_COMPAT = 95
    ANON_REVEALS = 10
    ANON_MESSAGES = 100
    POPULAR_RATING = 50
    PHOTOGRAPHER_COUNT = 5
    REPORTS_SENT = 1
    MSGLIKES_COUNT = 5


class BadgeDisplay:
    """Отображение значков."""

    INLINE_MAX = 5
    COLLECTION_MAX = 10


class BadgeColor:
    """Цвета значков по редкости."""

    COMMON = "#95a5a6"
    RARE = "#3498db"
    EPIC = "#9b59b6"
    LEGENDARY = "#f1c40f"
    FIRST_MATCH = "#e67e22"
    VERIFIED = "#2ecc71"


class Compatibility:
    """Константы расчёта совместимости."""

    BASE = 50
    MULTIPLIER = 60
    OFFSET = 40
    BONUS_THRESHOLD = 3
    BONUS = 5
    MIN = 35
    MAX = 99
    CACHE_TTL = 300.0
    MAX_CACHE_SIZE = 10000


class FireRating:
    """Пороги рейтинга огня."""

    LOW = 5
    MID = 20
    HIGH = 50


class ProgressBar:
    """Константы прогресс-бара."""

    SIZE = 10
    FILLED = "▰"
    EMPTY = "▱"


class Relationship:
    """Константы уровней отношений."""

    THRESHOLDS = [0, 15, 50, 150, 400]
    MAX_LEVEL = 4
    MILESTONES = {
        5: {"emoji": "💬", "name": "Первый разговор", "desc": "5 сообщений"},
        25: {"emoji": "🌙", "name": "Ночной разговор", "desc": "25 сообщений"},
        75: {"emoji": "📅", "name": "Неделя вместе", "desc": "75 сообщений"},
        100: {"emoji": "🔥", "name": "Сотня", "desc": "100 сообщений"},
        250: {"emoji": "💎", "name": "Полпути", "desc": "250 сообщений"},
    }


class AnonChat:
    """Константы анонимного чата."""

    RATE_LIMIT_WINDOW = 60.0
    RATE_LIMIT_MSG_PER_MIN = 30
    CLEANUP_CUTOFF = 300
    MAX_TRACKED_USERS = 10000


class Broadcast:
    """Константы рассылки."""

    BATCH_SIZE = 100
    DELAY = 0.05
    CONCURRENT = 10


class Admin:
    """Константы админ-панели."""

    RECENT_USERS_LIMIT = 20
    RECENT_REPORTS_LIMIT = 10
    TOP_COLLECTORS_LIMIT = 10


class Health:
    """Константы health-сервера."""

    PORT = 8080
    HTTP_NOT_READY = 503


class Verification:
    """Константы верификации через кружочек."""

    GESTURES = ["✌️", "👍", "🤙", "👌", "🤘", "✊", "🖐️", "👋"]
    MAX_ATTEMPTS = 3


class EMOJI:
    """Все emoji бота."""

    MALE = "👨"
    FEMALE = "👩"
    UNKNOWN_GENDER = "🧑"

    VERIFIED = "✅"
    BANNED = "🚫"
    ACTIVE = "🟢"
    INACTIVE = "🔴"

    LOCATION = "📍"
    INTERESTS = "🏷"
    BIO = "📝"

    FIRE_LOW = "✨"
    FIRE_MID = "🔥"
    FIRE_HIGH = "🔥🔥"
    FIRE_MAX = "🔥🔥🔥"
    RATING_STAR = "⭐"

    COMPAT = "💞"
    MATCH = "🎉"
    DIAMOND = "💎"
    CROWN = "👑"

    LIKE = "❤️"
    DISLIKE = "👎"
    MESSAGE_LIKE = "💬"
    PHOTOS = "📸"
    REPORT = "🚩"
    STOP = "⏹"
    BACK = "↩️"
    ADD = "➕"
    DONE = "✔️"
    SKIP = "⏭"
    REVEAL = "👀"
    DELETE = "🗑"

    NEW_BADGE = "🎉"
    BADGE_TROPHY = "🏆"
    HEART = "💝"
    SPARK = "🔥"
    SHIELD = "🛡️"
    CALENDAR = "📅"
    CHAT = "💬"
    CAMERA = "📸"
    MASK = "🎭"
    SPEAKER = "🗣️"
    BOOK = "📖"
    TROPHY = "🏆"
    HUNDRED = "💯"

    SEARCH = "🔍"
    BLIND_DATE = "🎭"
    LIKES_INBOX = "💌"
    MATCHES = "💞"
    PROFILE = "👤"
    BADGES = "🏆"
    SETTINGS = "⚙️"
    SUPPORT = "📩"
    ADMIN = "🛡"

    PROGRESS_FILLED = "▰"
    PROGRESS_EMPTY = "▱"


class MenuText:
    """Тексты кнопок главного меню."""

    SEARCH = f"{EMOJI.SEARCH} Смотреть анкеты"
    BLIND_DATE = f"{EMOJI.BLIND_DATE} Свидание вслепую"
    LIKES_INBOX = f"{EMOJI.LIKES_INBOX} Кто меня лайкнул"
    MATCHES = f"{EMOJI.MATCHES} Мэтчи"
    MY_PROFILE = f"{EMOJI.PROFILE} Моя анкета"
    BADGES = f"{EMOJI.BADGES} Артефакты"
    SETTINGS = f"{EMOJI.SETTINGS} Настройки"
    SUPPORT = f"{EMOJI.SUPPORT} Поддержка"
    CANCEL_SEARCH = f"{EMOJI.STOP} Отменить поиск"
    STOP_BLIND_DATE = f"{EMOJI.STOP} Завершить свидание"
    MENU = "📋 Меню"


class RELATIONSHIP_LEVEL_NAMES:
    """Названия уровней отношений."""

    _names = {
        0: "💫 Общение",
        1: "💌 Симпатия",
        2: f"{EMOJI.FIRE_MID} Интерес",
        3: f"{EMOJI.COMPAT} Близость",
        4: f"{EMOJI.CROWN} Пара",
    }

    @classmethod
    def get(cls, level: int) -> str:
        return cls._names.get(level, cls._names[0])


class RARITY_LABELS:
    """Человекочитаемые названия редкостей."""

    _labels = {
        "common": "Обычный",
        "rare": "Редкий",
        "epic": "Эпический",
        "legendary": "Легендарный",
    }

    @classmethod
    def get(cls, rarity: str) -> str:
        return cls._labels.get(rarity, rarity)


class RARITY_COLORS:
    """Цвета значков по редкости."""

    _colors = {
        "common": BadgeColor.COMMON,
        "rare": BadgeColor.RARE,
        "epic": BadgeColor.EPIC,
        "legendary": BadgeColor.LEGENDARY,
    }

    @classmethod
    def get(cls, rarity: str) -> str:
        return cls._colors.get(rarity, BadgeColor.COMMON)


class SUPPORT_CATEGORY_NAMES:
    """Названия категорий поддержки."""

    _names = {
        "report": "🧧 Жалоба на пользователя",
        "rights": "🗣 Нарушение моих прав",
        "other": "❓ Другое",
    }

    @classmethod
    def get(cls, category: str) -> str:
        return cls._names.get(category, "❓ Другое")


class SUPPORT_CATEGORY_DESCRIPTIONS:
    """Описания категорий поддержки."""

    _descs = {
        "report": "опасное поведение, нарушения",
        "rights": "используют мои данные",
        "other": "вопросы, лагает/не работает, верификация, юр. запросы",
    }

    @classmethod
    def get(cls, category: str) -> str:
        return cls._descs.get(category, "")


class Message:
    """Часто используемые сообщения."""

    CREATE_PROFILE_FIRST = "Сначала создай анкету, /start."
    WELCOME_BACK = "С возвращением! 🔥 Выбирай, что делаем дальше."
    NO_MORE_PROFILES = "Пока новых анкет нет 🙈 Загляни позже или измени фильтры в ⚙️ Настройках."
    NO_LIKES = "Пока никто не лайкнул 😅 Активность повышает шансы, листай ленту!"
    NO_MATCHES = "Мэтчей пока нет 💔 Но всё впереди! Листай анкеты 🔍"
    MAX_PHOTOS = "Максимум 5 фото 🙂"
    MAX_INTERESTS = "Максимум 5 🙂"
    NAME_TOO_LONG = "Слишком длинно 🙂 До 32 символов."
    AGE_INVALID = "Введи возраст числом (14–99)."
    AGE_RANGE_INVALID = "Диапазон: 14–99, мин < макс"
    SEND_PHOTO = "Нужно именно фото 📷 (как изображение, не файлом)."
    SEND_PHOTO_OR_SKIP = "Отправь фото 📷 или нажми «Пропустить»."
    PROFILE_COMPLETE = "✨ Готово! Вот твоя анкета:\n"

    LETS_GO = "Поехали искать! Жми «🔍 Смотреть анкеты»."
    MATCH_ACHIEVED = "🎉 Мэтч!"
    LIKE_SENT = "❤️"
    DISLIKE_SENT = "👎"
    REPORT_SENT = "Спасибо, жалоба отправлена 🚩"
    SEARCH_STOPPED = "Остановились ⏹ Возвращайся в любой момент!"
    BLIND_DATE_INTRO = """🎭 Свидание вслепую
Я соединю тебя с другим человеком, анонимно.
Имя, фото и анкета скрыты: вы просто общаетесь вживую.
Понравится разговор, жмите «🎭 Открыться». Если согласятся оба,
вы увидите анкеты друг друга и попадёте в мэтчи 💞"""
    BLIND_DATE_SEARCHING = """🔎 Ищу собеседника… Соединю, как только кто-то ещё зайдёт.
Можешь пока листать ленту, я напишу, когда найду."""
    BLIND_DATE_FOUND = """✨ Собеседник найден!
Общайтесь анонимно, просто пиши сюда,
я всё передам. Можно отправлять и фото, и голосовые 🙂"""
    BLIND_DATE_REVEAL_PROMPT = "Когда захочешь раскрыть анкету, жми «🎭 Открыться»."
    BLIND_DATE_ENDED = "🎭 Свидание завершено. Захочешь ещё, жми «🎭 Свидание вслепую»."
    BLIND_DATE_REVEAL_WAIT = "Ты открыл(а)ся 👀 Ждём, решится ли собеседник…"
    BLIND_DATE_REVEAL_REQUEST = """👀 Собеседник хочет открыться! Нажми «🎭 Открыться» в ответ,
если тоже хочешь увидеть анкету."""
    BLIND_DATE_BOTH_REVEALED = "🎭 ➡️ 💞 Вы оба открылись! Теперь вы в мэтчах. Удачи! 🔥"
    RATE_LIMIT_WAIT = "⏳ Слишком быстро! Подожди {} сек."
    DELIVERY_FAILED = "Не получилось доставить сообщение собеседнику 😕"
    ALREADY_IN_SESSION = "Ты уже на свидании 🎭 Просто пиши, я передам собеседнику."
    ALREADY_SEARCHING = "Уже ищу тебе собеседника 🔎 Немного терпения…"
    NOT_IN_SESSION = "Ты сейчас не на свидании 🙂"
    SEARCH_CANCELLED = "Поиск отменён 🙂"
    TICKET_SENT = """✅ Обращение отправлено!
Администратор рассмотрит его в ближайшее время.
Ответ придёт в этот чат."""
    TICKET_CANCELLED = "↩️ Обращение отменено."
    REPLY_CANCELLED = "↩️ Ответ отменён."
    VERIFICATION_SENT = """✅ Заявка на верификацию отправлена!
Обычно проверка занимает до 24 часов."""
    VERIFICATION_APPROVED = "🎉 Ваша анкета верифицирована! Теперь у вас есть галочка ✅"
    VERIFICATION_REJECTED = "❌ Верификация отклонена. Попробуйте ещё раз через /myprofile → ✅ Верификация"
    VERIFICATION_REMOVED = "ℹ️ Ваша верификация была снята администратором."
    ACCOUNT_DELETED = "🗑 Аккаунт удалён. До встречи! 👋"
    NO_BADGES = """🏆 У тебя пока нет артефактов.
Активничай в боте, и они появятся!"""
    BADGE_COLLECTION_TITLE = "🏆 Твои артефакты ({}) "
    BADGE_NEW = "🎉 Новый артефакт! "
    BADGE_RARITY_LABEL = "Редкость: {}"
    FALLBACK = "Не понял команду 😅 Используй меню или /help"
    ADMIN_ONLY = "⛔ Только для админов"
    USER_NOT_FOUND = "❌ Пользователь не найден"

    MILESTONE_FIRST_TALK = "💬 <b>Первый разговор!</b>\nВы обменялись 5 сообщениями. Отличное начало!"
    MILESTONE_NIGHT_TALK = "🌙 <b>Ночной разговор!</b>\n25 сообщений, вы уже не незнакомцы."
    MILESTONE_WEEK_TOGETHER = "📅 <b>Неделя вместе!</b>\n75 сообщений, привычка общаться друг с другом."
    MILESTONE_HUNDRED = "🔥 <b>Сотня!</b>\n100 сообщений, это уже серьёзно."
    MILESTONE_HALF_WAY = "💎 <b>Полпути!</b>\n250 сообщений, почти пара!"


class Defaults:
    """Значения по умолчанию для полей БД."""

    STREAK = 0
    RATING = 0
    ANON_MESSAGES = 0
    ACTIVE = True
    VERIFIED = False
    IS_BANNED = False
    NAME = "Без имени"
    CITY = "—"
    BIO = ""
    INTERESTS = ""
    PHOTO_ID = None
    USERNAME = None
    AGE = None
    GENDER = None
    SEEKING = None


class Separator:
    """Разделители строк."""

    COMMA = ","
    SPACE = " "
    NEWLINE = "\n"
    CALLBACK = ":"
    DASH = "-"


class Format:
    """Форматные строки."""

    CONTACT_USERNAME = "@{}"
    CONTACT_LINK = '<a href="tg://user?id={}">{}</a>'
    ID_LABEL = "ID:{}"
    PHOTO_COUNT = "\n📸 Фото в анкете: {}"
    COMPAT_PERCENT = "{}%"
    PROGRESS_BAR = "{}{} {}%"
    BADGE_EXTRA = " +{}"
    BADGE_INLINE = "\n🏆 {}{}"
    MATCH_COUNT = "💞 <b>Твои мэтчи ({}):</b>"
    INCOMING_LIKES = "💌 Тебя лайкнули: <b>{}</b>. Показываю по одному:"
    PHOTO_ADDED = "✅ Фото добавлено! ({}/{})"
    PHOTOS_REMAINING = "Можно ещё {} шт. или нажми «Пропустить»."
    AGE_FILTER_SAVED = "✅ Фильтр возраста: {}–{}"
    SEEKING_SAVED = "✅ Сохранено"
    BAN_SUCCESS = "🚫 {} (ID: {}) забанен."
    UNBAN_SUCCESS = "✅ {} (ID: {}) разбанен."
    UNVERIFY_SUCCESS = "✅ Верификация снята у {} (ID: {})."
    REPLY_SENT = "✅ Ответ отправлен пользователю {}."
    REPLY_FAILED = "❌ Не удалось отправить: {}"
    BROADCAST_USAGE = "Использование: /broadcast Ваше сообщение"
    BAN_USAGE = "Использование: /ban 123456789"
    UNBAN_USAGE = "Использование: /unban 123456789"
    UNVERIFY_USAGE = "Использование: /unverify 123456789"
    TICKET_CAPTION = """📩 Тикет #{}
Категория: {}
Пользователь: {} ({})
ID: {}
Сообщение:
{}"""
    ADMIN_REPLY_PROMPT = """✏️ Напиши ответ пользователю {}:
(или /cancel для отмены)"""
    SUPPORT_REPLY = """💬 <b>Ответ от поддержки:</b>
{}"""
    STATS_HEADER = "📊 <b>Статистика Искра</b>"
    STATS_USERS = "\n👥 Всего пользователей: <b>{}</b>"
    STATS_ACTIVE = "\n🟢 Активных: <b>{}</b>"
    STATS_NEW_TODAY = "\n🆕 Новых сегодня: <b>{}</b>"
    STATS_BANNED = "\n🚫 Забанено: <b>{}</b>\n"
    STATS_LIKES = "\n❤️ Лайков: <b>{}</b>"
    STATS_MATCHES = "\n💞 Мэтчей: <b>{}</b>"
    STATS_REPORTS = "\n🚩 Жалоб: <b>{}</b>\n"
    STATS_MALES = "\n👨 Парней: <b>{}</b>"
    STATS_FEMALES = "\n👩 Девушек: <b>{}</b>"
    REL_STATUS_POINTS = "Очков: {} / {}"
    REL_STATUS_BAR = "{} {}%"
    VERIFICATION_REQUEST = """🎥 <b>Верификация через кружочек</b>
Запиши <b>кружочек</b> (видеосообщение) и покажи в кадре жест: <b>{}</b>
Лицо должно быть хорошо видно. Жест обязателен."""
    LIKE_NOTIFICATION = "💌 Кто-то проявил симпатию!\nСовместимость с этим человеком: <b>{}%</b>."
    LIKE_NOTIFICATION_WITH_MESSAGE = "💬 Подсказка для первого сообщения:\n<i>{}</i>"
    LIKE_NOTIFICATION_FOOTER = "\nОткрой «💌 Кто меня лайкнул», чтобы посмотреть анкету."
    MATCH_ANNOUNCE = """🎉 <b>Это мэтч!</b> {}
Вы понравились друг другу с <b>{}</b>, {}.
{}
{}
📨 Контакт: {}
💬 С чего начать:
<i>{}</i>"""
    PROFILE_NAME_AGE = "<b>{}</b>{}, {} {}  •  {} {}"
    PROFILE_INTERESTS = "\n🏷 {}"
    PROFILE_BIO = "\n📝 {}"
    PROFILE_RATING = "\n{}  Симпатий: {}"
    PROFILE_COMPAT = "\n💞 Совместимость: <b>{}%</b>\n{}"
    PROFILE_COMMON = "🏷 Общее: "
    BROADCAST_STATUS = "📣 <b>Рассылка...</b> {}/{}\n✅ Доставлено: {}\n❌ Ошибок: {}"
    BROADCAST_DONE = """📣 <b>Рассылка завершена</b>

✅ Доставлено: {}
❌ Ошибок: {}"""
    BROADCAST_START = "📣 Отправляю {} пользователям..."
    BROADCAST_PREFIX = "📢 "


RELATIONSHIP_THRESHOLDS = Relationship.THRESHOLDS


class NSFWThreshold:
    """Пороги NSFW-модерации."""

    NUDITY = 0.75
    VIOLENCE = 0.70
    SUSPICIOUS = 0.40
    AUTO_BAN_STRIKES = 3


class NSFWMessage:
    """Сообщения NSFW-модерации."""

    BLOCKED = "🚫 Контент заблокирован: обнаружен запрещённый материал."
    PROFILE_PHOTO_REJECTED = "🚫 Фото не прошло модерацию. Загрузите другое фото."
    SUSPICIOUS_FLAGGED = "⚠️ Фото отправлено на ручную проверку модератором."
