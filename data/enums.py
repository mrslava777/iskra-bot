"""Enums для бота Искра — замена магических строк на типизированные значения.

FIX: убраны runtime-импорты из data.constants — предотвращает циклические зависимости.
Все строковые значения вынесены в inline-константы.
"""
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE КОНСТАНТЫ (были импортированы из data.constants, вызывали циклы)
# ═══════════════════════════════════════════════════════════════════════════════

_EMOJI_MALE = "👨"
_EMOJI_FEMALE = "👩"
_EMOJI_UNKNOWN = "🧑"
_EMOJI_FIRE_MID = "🔥"
_EMOJI_COMPAT = "💞"
_EMOJI_CROWN = "👑"

_RARITY_ORDER = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}
_RARITY_EMOJI = {"common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡"}
_RARITY_LABELS = {
    "common": "Обычный",
    "rare": "Редкий",
    "epic": "Эпический",
    "legendary": "Легендарный",
}
_RARITY_COLORS = {
    "common": "#95a5a6",
    "rare": "#3498db",
    "epic": "#9b59b6",
    "legendary": "#f1c40f",
}

_SUPPORT_NAMES = {
    "report": "🧧 Жалоба на пользователя",
    "rights": "🗣 Нарушение моих прав",
    "other": "❓ Другое",
}
_SUPPORT_DESCS = {
    "report": "опасное поведение, нарушения",
    "rights": "используют мои данные",
    "other": "вопросы, лагает/не работает, верификация, юр. запросы",
}

_REL_NAMES = {
    0: "💫 Общение",
    1: "💌 Симпатия",
    2: f"{_EMOJI_FIRE_MID} Интерес",
    3: f"{_EMOJI_COMPAT} Близость",
    4: f"{_EMOJI_CROWN} Пара",
}
_REL_THRESHOLDS = [0, 50, 150, 350, 750]


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class Gender(Enum):
    """Пол пользователя."""
    MALE = "m"
    FEMALE = "f"
    ANY = "any"

    @property
    def emoji(self) -> str:
        return {
            Gender.MALE: _EMOJI_MALE,
            Gender.FEMALE: _EMOJI_FEMALE,
            Gender.ANY: _EMOJI_UNKNOWN,
        }[self]


class Seeking(Enum):
    """Кого ищет пользователь."""
    MALE = "m"
    FEMALE = "f"
    ANY = "any"


class Rarity(Enum):
    """Редкость значка (артефакта)."""
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"

    @property
    def order(self) -> int:
        return _RARITY_ORDER[self.value]

    @property
    def emoji(self) -> str:
        return _RARITY_EMOJI[self.value]

    @property
    def label(self) -> str:
        return _RARITY_LABELS[self.value]

    @property
    def color(self) -> str:
        return _RARITY_COLORS[self.value]


class TicketStatus(Enum):
    """Статус тикета поддержки."""
    OPEN = "open"
    REPLIED = "replied"
    CLOSED = "closed"


class SupportCategory(Enum):
    """Категория обращения в поддержку."""
    REPORT = "report"
    RIGHTS = "rights"
    OTHER = "other"

    @property
    def display_name(self) -> str:
        return _SUPPORT_NAMES.get(self.value, "❓ Другое")

    @property
    def description(self) -> str:
        return _SUPPORT_DESCS.get(self.value, "")


class CallbackPrefix(Enum):
    """Префиксы callback_data кнопок."""
    SWIPE = "sw"
    LIKE = "lk"
    EDIT = "ed"
    EDIT_INTEREST = "edint"
    PHOTO = "ph"
    REG_GENDER = "rgender"
    REG_SEEKING = "rseek"
    REG_INTEREST = "rint"
    SETTINGS = "set"
    SETTINGS_SEEKING = "setseek"
    VERIFY = "vrf"
    SUPPORT = "sup"
    SUPPORT_REPLY = "supreply"
    ADMIN = "adm"
    BADGE = "bdg"
    ANON = "anon"
    REG_PHOTO = "regph"
    RELATIONSHIP = "rel"

    def __str__(self) -> str:
        return f"{self.value}:"

    def with_param(self, *parts: str | int) -> str:
        """Формирует callback_data с параметрами."""
        return ":".join([self.value, *(str(p) for p in parts)])


class Command(Enum):
    """Команды бота."""
    START = "/start"
    MYPROFILE = "/myprofile"
    BADGES = "/badges"
    HELP = "/help"
    STOP = "/stop"
    ADMIN = "/admin"
    BROADCAST = "/broadcast"
    BAN = "/ban"
    UNBAN = "/unban"
    UNVERIFY = "/unverify"
    SUPPORT = "/support"
    CANCEL = "/cancel"


class RelationshipLevel(Enum):
    """Уровни отношений между мэтчами — от общения до пары."""
    TALKING = 0
    LIKING = 1
    INTEREST = 2
    CLOSENESS = 3
    COUPLE = 4

    @property
    def name_ru(self) -> str:
        return _REL_NAMES.get(self.value, _REL_NAMES[0])

    @property
    def threshold(self) -> int:
        return _REL_THRESHOLDS[self.value]


class UserStatus(Enum):
    """Статус пользователя в системе."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class SwipeAction(Enum):
    """Действия при свайпе в ленте."""
    LIKE = "like"
    DISLIKE = "dislike"
    MESSAGE_LIKE = "msglike"
    PHOTOS = "photos"
    REPORT = "report"
    STOP = "stop"


class LikeResponse(Enum):
    """Ответ на входящий лайк."""
    YES = "yes"
    NO = "no"


class PhotoAction(Enum):
    """Действия с фотографиями."""
    ADD = "add"
    DELETE = "del"
    BACK = "back"


class VerifyAction(Enum):
    """Действия верификации админом."""
    APPROVE = "approve"
    REJECT = "reject"


class AdminAction(Enum):
    """Действия в админ-панели."""
    MENU = "menu"
    STATS = "stats"
    USERS = "users"
    VERIFIED = "verified"
    UNVERIFY = "unverify"
    BAN = "ban"
    REPORTS = "reports"
    DO_BAN = "doban"
    BROADCAST = "broadcast"
    BADGES = "badges"


class BadgeAction(Enum):
    """Действия в разделе артефактов."""
    PROGRESS = "progress"
    COLLECTION = "collection"
    BACK = "back"


class AnonAction(Enum):
    """Действия в анонимном чате."""
    REVEAL = "reveal"
    STOP = "stop"
    CANCEL_QUEUE = "cancelq"


class SettingsAction(Enum):
    """Действия в настройках."""
    TOGGLE = "toggle"
    AGE_FILTER = "age"
    SEEKING = "seeking"
    SUPPORT = "support"
    DELETE = "delete"
    DELETE_CONFIRM = "delete_confirm"
    DELETE_CANCEL = "delete_cancel"


class EditField(Enum):
    """Поля анкеты для редактирования."""
    NAME = "name"
    AGE = "age"
    CITY = "city"
    BIO = "bio"
    INTERESTS = "interests"
    PHOTOS = "photos"
    VERIFY = "verify"


# ═══════════════════════════════════════════════════════════════════════════════
# ОБРАТНЫЕ МАППИНГИ (для совместимости с существующим кодом)
# ═══════════════════════════════════════════════════════════════════════════════

RARITY_ORDER: dict[Rarity, int] = {
    Rarity.COMMON: 0,
    Rarity.RARE: 1,
    Rarity.EPIC: 2,
    Rarity.LEGENDARY: 3,
}

RARITY_EMOJI: dict[Rarity, str] = {
    Rarity.COMMON: "⚪",
    Rarity.RARE: "🔵",
    Rarity.EPIC: "🟣",
    Rarity.LEGENDARY: "🟡",
}
