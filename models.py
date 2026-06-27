"""Модели данных для бота Искра.

Все Repository возвращают модели вместо dict.
Этап 4 рефакторинга.
"""
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from data.constants import Relationship, Defaults
from data.enums import Rarity, TicketStatus


@dataclass
class User:
    """Модель пользователя."""
    tg_id: int
    username: Optional[str] = Defaults.USERNAME
    name: Optional[str] = Defaults.NAME
    age: Optional[int] = Defaults.AGE
    gender: Optional[str] = Defaults.GENDER
    seeking: Optional[str] = Defaults.SEEKING
    city: Optional[str] = Defaults.CITY
    bio: Optional[str] = Defaults.BIO
    interests: Optional[str] = Defaults.INTERESTS
    photo_id: Optional[str] = Defaults.PHOTO_ID
    active: bool = Defaults.ACTIVE
    verified: bool = Defaults.VERIFIED
    is_banned: bool = Defaults.IS_BANNED
    created_at: int = 0
    last_active: int = 0
    streak: int = Defaults.STREAK
    rating: int = Defaults.RATING
    daily_q: int = Defaults.DAILY_Q
    daily_a: Optional[str] = Defaults.DAILY_A
    anon_messages_count: int = Defaults.ANON_MESSAGES

    @property
    def is_complete(self) -> bool:
        """Проверяет, заполнена ли анкета."""
        return bool(self.name and self.photo_id)

    @property
    def interests_list(self) -> list[int]:
        """Возвращает список ID интересов."""
        if not self.interests:
            return []
        return [int(x.strip()) for x in self.interests.split(",") if x.strip().isdigit()]


@dataclass
class Photo:
    """Модель фотографии."""
    id: int
    tg_id: int
    photo_id: str
    position: int = 0


@dataclass
class Like:
    """Модель лайка/дизлайка."""
    id: int
    from_id: int
    to_id: int
    is_like: bool = True
    message: Optional[str] = None
    created_at: int = 0

    @property
    def is_mutual(self) -> bool:
        """Проверяет, является ли лайк взаимным (требует доп. проверки в БД)."""
        return False


@dataclass
class Match:
    """Модель мэтча."""
    id: int
    a_id: int
    b_id: int
    created_at: int = 0

    def other_id(self, viewer_id: int) -> int:
        """Возвращает ID партнёра."""
        return self.b_id if self.a_id == viewer_id else self.a_id


@dataclass
class Relationship:
    """Модель отношений между пользователями."""
    id: int
    user1_id: int
    user2_id: int
    points: int = 0
    level: int = 0
    created_at: int = 0

    THRESHOLDS = Relationship.THRESHOLDS

    @property
    def next_threshold(self) -> int:
        """Возвращает следующий порог уровня."""
        if self.level < len(self.THRESHOLDS) - 1:
            return self.THRESHOLDS[self.level + 1]
        return 0

    @property
    def progress_percent(self) -> int:
        """Возвращает процент прогресса к следующему уровню."""
        if self.next_threshold == 0:
            return 100
        return min(100, int(self.points / self.next_threshold * 100))

    @property
    def level_name(self) -> str:
        """Возвращает название текущего уровня."""
        from data.constants import RELATIONSHIP_LEVEL_NAMES
        return RELATIONSHIP_LEVEL_NAMES.get(self.level)


@dataclass
class SupportTicket:
    """Модель тикета поддержки."""
    id: int
    tg_id: int
    category: str
    text: str
    photo_id: Optional[str] = None
    reply: Optional[str] = None
    status: str = TicketStatus.OPEN.value
    created_at: int = 0

    @property
    def is_open(self) -> bool:
        return self.status == TicketStatus.OPEN.value

    @property
    def is_replied(self) -> bool:
        return self.status == TicketStatus.REPLIED.value


@dataclass
class Badge:
    """Модель значка/артефакта."""
    id: str
    name: str
    description: str
    icon: str
    rarity: str
    color: str

    @property
    def rarity_emoji(self) -> str:
        from data.enums import RARITY_EMOJI, Rarity
        return RARITY_EMOJI.get(Rarity(self.rarity), "⚪")

    @property
    def rarity_label(self) -> str:
        from data.constants import RARITY_LABELS
        return RARITY_LABELS.get(self.rarity, self.rarity)

    @property
    def rarity_sort_key(self) -> int:
        from data.enums import RARITY_ORDER, Rarity
        return RARITY_ORDER.get(Rarity(self.rarity), 0)


@dataclass
class UserBadge:
    """Модель выданного значка пользователю."""
    tg_id: int
    badge_id: str
    awarded_at: int = 0


@dataclass
class Notification:
    """Модель уведомления."""
    tg_id: int
    text: str
    photo_id: Optional[str] = None
    reply_markup: Optional[object] = None


@dataclass
class AnonSession:
    """Модель анонимной сессии."""
    id: int
    a_id: int
    b_id: int
    a_reveal: bool = False
    b_reveal: bool = False
    started_at: int = 0
    ended_at: Optional[int] = None

    def is_revealed_by(self, user_id: int) -> bool:
        return self.a_reveal if self.a_id == user_id else self.b_reveal

    def partner_id(self, user_id: int) -> int:
        return self.b_id if self.a_id == user_id else self.a_id

    @property
    def both_revealed(self) -> bool:
        return self.a_reveal and self.b_reveal


@dataclass
class Report:
    """Модель жалобы."""
    id: int
    from_id: int
    to_id: int
    created_at: int = 0


@dataclass
class ShownProfile:
    """Модель показанного профиля."""
    from_id: int
    to_id: int
    shown_at: int = 0


@dataclass
class AnonQueueEntry:
    """Модель записи в очереди анонимного чата."""
    tg_id: int
    queued_at: int = 0


@dataclass
class AdminStats:
    """Модель статистики админ-панели."""
    users: int = 0
    active: int = 0
    likes: int = 0
    matches: int = 0
    new_today: int = 0
    banned: int = 0
    reports: int = 0
    males: int = 0
    females: int = 0


@dataclass
class UserListItem:
    """Модель элемента списка пользователей (для админки)."""
    tg_id: int
    name: Optional[str] = None
    username: Optional[str] = None
    age: Optional[int] = None
    active: bool = True
    is_banned: bool = False


@dataclass
class BadgeStats:
    """Модель статистики значков."""
    badge_id: str
    count: int = 0


@dataclass
class TopCollector:
    """Модель топ-коллекционера значков."""
    tg_id: int
    count: int = 0
