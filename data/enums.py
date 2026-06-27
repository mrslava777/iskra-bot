"""Enums для бота Искра — замена магических строк на типизированные значения."""
from enum import Enum


class Gender(Enum):
    """Пол пользователя."""
    MALE = "m"
    FEMALE = "f"
    ANY = "any"

    @property
    def emoji(self) -> str:
        from data.constants import EMOJI
        return {
            Gender.MALE: EMOJI.MALE,
            Gender.FEMALE: EMOJI.FEMALE,
            Gender.ANY: EMOJI.UNKNOWN_GENDER,
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
        return RARITY_ORDER[self]

    @property
    def emoji(self) -> str:
        from data.constants import EMOJI
        return RARITY_EMOJI[self]

    @property
    def label(self) -> str:
        from data.constants import RARITY_LABELS
        return RARITY_LABELS[self]

    @property
    def color(self) -> str:
        from data.constants import RARITY_COLORS
        return RARITY_COLORS[self]


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
        from data.constants import SUPPORT_CATEGORY_NAMES
        return SUPPORT_CATEGORY_NAMES[self]

    @property
    def description(self) -> str:
        from data.constants import SUPPORT_CATEGORY_DESCRIPTIONS
        return SUPPORT_CATEGORY_DESCRIPTIONS[self]


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
    """Уровни отношений между мэтчами."""
    STRANGERS = 0
    FRIENDS = 1
    CLOSE_FRIENDS = 2
    BEST_FRIENDS = 3
    SOULMATES = 4

    @property
    def name_ru(self) -> str:
        from data.constants import RELATIONSHIP_LEVEL_NAMES
        return RELATIONSHIP_LEVEL_NAMES[self]

    @property
    def threshold(self) -> int:
        from data.constants import RELATIONSHIP_THRESHOLDS
        return RELATIONSHIP_THRESHOLDS[self.value]


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
    DAILY = "daily"
    DELETE_DAILY = "del_daily"
    VERIFY = "verify"


# Обратные маппинги для быстрого доступа
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
