"""Система достижений (Артефакты) Искры.

Каждый значок имеет:
  - id: уникальный ключ
  - name: название для пользователя
  - description: описание как получить
  - icon: emoji или текстовая иконка
  - rarity: common / rare / epic / legendary
  - condition: функция-проверка (user_row, stats) -> bool
  - color: hex-цвет для оформления
  - progress_info: (label, current_key, target) для отображения прогресса
"""
from typing import Callable

BadgeDef = dict


def _check_first_match(user, stats):
    return stats.get("matches", 0) >= 1


def _check_ten_matches(user, stats):
    return stats.get("matches", 0) >= 10


def _check_fifty_matches(user, stats):
    return stats.get("matches", 0) >= 50


def _check_first_like(user, stats):
    return stats.get("likes_sent", 0) >= 1


def _check_hundred_likes(user, stats):
    return stats.get("likes_sent", 0) >= 100


def _check_streak_7(user, stats):
    return (user["streak"] or 0) >= 7


def _check_streak_30(user, stats):
    return (user["streak"] or 0) >= 30


def _check_high_compat(user, stats):
    return stats.get("max_compat", 0) >= 95


def _check_revealer(user, stats):
    return stats.get("anon_reveals", 0) >= 10


def _check_chatter(user, stats):
    return stats.get("anon_messages", 0) >= 100


def _check_popular(user, stats):
    return (user["rating"] or 0) >= 50


def _check_verified(user, stats):
    return bool(user["verified"])


def _check_profile_complete(user, stats):
    checks = [
        user["name"],
        user["age"],
        user["city"],
        user["bio"],
        user["interests"],
        user["daily_a"],
    ]
    return sum(1 for c in checks if c) >= 5


def _check_photographer(user, stats):
    return stats.get("photo_count", 0) >= 5


def _check_reporter(user, stats):
    return stats.get("reports_sent", 0) >= 1


def _check_icebreaker(user, stats):
    return stats.get("msglikes", 0) >= 5


BADGES: list[BadgeDef] = [
    # --- Обычные (common) ---
    {
        "id": "first_like",
        "name": "Первая симпатия",
        "description": "Поставь свой первый лайк",
        "icon": "💝",
        "rarity": "common",
        "condition": _check_first_like,
        "color": "#95a5a6",
        "progress": ("лайков", "likes_sent", 1),
    },
    {
        "id": "profile_complete",
        "name": "Открытая книга",
        "description": "Заполни 5 из 6 полей анкеты",
        "icon": "📖",
        "rarity": "common",
        "condition": _check_profile_complete,
        "color": "#95a5a6",
        "progress": None,  # бинарный (да/нет)
    },
    {
        "id": "first_match",
        "name": "Первая Искра",
        "description": "Получи первый мэтч",
        "icon": "🔥",
        "rarity": "common",
        "condition": _check_first_match,
        "color": "#e67e22",
        "progress": ("мэтчей", "matches", 1),
    },
    {
        "id": "reporter",
        "name": "Страж порядка",
        "description": "Отправь жалобу на нарушителя",
        "icon": "🛡️",
        "rarity": "common",
        "condition": _check_reporter,
        "color": "#95a5a6",
        "progress": ("жалоб", "reports_sent", 1),
    },
    # --- Редкие (rare) ---
    {
        "id": "streak_7",
        "name": "Неделя в огне",
        "description": "7 дней активности подряд",
        "icon": "📅",
        "rarity": "rare",
        "condition": _check_streak_7,
        "color": "#3498db",
        "progress": ("дней подряд", "streak", 7),
    },
    {
        "id": "ten_matches",
        "name": "Сердцеед",
        "description": "10 мэтчей",
        "icon": "💘",
        "rarity": "rare",
        "condition": _check_ten_matches,
        "color": "#e74c3c",
        "progress": ("мэтчей", "matches", 10),
    },
    {
        "id": "icebreaker",
        "name": "Мастер знакомств",
        "description": "5 лайков с сообщением",
        "icon": "💬",
        "rarity": "rare",
        "condition": _check_icebreaker,
        "color": "#3498db",
        "progress": ("лайков с сообщением", "msglikes", 5),
    },
    {
        "id": "photographer",
        "name": "Фотограф",
        "description": "Загрузи 5 фото в анкету",
        "icon": "📸",
        "rarity": "rare",
        "condition": _check_photographer,
        "color": "#3498db",
        "progress": ("фото", "photo_count", 5),
    },
    {
        "id": "verified",
        "name": "Проверенный",
        "description": "Пройди верификацию профиля",
        "icon": "✅",
        "rarity": "rare",
        "condition": _check_verified,
        "color": "#2ecc71",
        "progress": None,  # бинарный
    },
    # --- Эпические (epic) ---
    {
        "id": "popular",
        "name": "Звезда",
        "description": "Получи 50 лайков",
        "icon": "⭐",
        "rarity": "epic",
        "condition": _check_popular,
        "color": "#9b59b6",
        "progress": ("лайков получено", "rating", 50),
    },
    {
        "id": "high_compat",
        "name": "Идеальная Пара",
        "description": "Найди анкету с 95%+ совместимостью",
        "icon": "💎",
        "rarity": "epic",
        "condition": _check_high_compat,
        "color": "#9b59b6",
        "progress": ("% совместимости", "max_compat", 95),
    },
    {
        "id": "revealer",
        "name": "Открывашка",
        "description": "10 раз открылся на свидании вслепую",
        "icon": "🎭",
        "rarity": "epic",
        "condition": _check_revealer,
        "color": "#9b59b6",
        "progress": ("открытий", "anon_reveals", 10),
    },
    {
        "id": "chatter",
        "name": "Болтун",
        "description": "100 сообщений в анонимном чате",
        "icon": "🗣️",
        "rarity": "epic",
        "condition": _check_chatter,
        "color": "#9b59b6",
        "progress": ("сообщений", "anon_messages", 100),
    },
    # --- Легендарные (legendary) ---
    {
        "id": "streak_30",
        "name": "Легенда Искры",
        "description": "30 дней активности подряд",
        "icon": "👑",
        "rarity": "legendary",
        "condition": _check_streak_30,
        "color": "#f1c40f",
        "progress": ("дней подряд", "streak", 30),
    },
    {
        "id": "fifty_matches",
        "name": "Король/Королева мэтчей",
        "description": "50 мэтчей",
        "icon": "🏆",
        "rarity": "legendary",
        "condition": _check_fifty_matches,
        "color": "#f1c40f",
        "progress": ("мэтчей", "matches", 50),
    },
    {
        "id": "hundred_likes",
        "name": "Щедрая душа",
        "description": "Поставь 100 лайков",
        "icon": "💯",
        "rarity": "legendary",
        "condition": _check_hundred_likes,
        "color": "#f1c40f",
        "progress": ("лайков", "likes_sent", 100),
    },
]

# Индекс для быстрого доступа
BADGE_BY_ID: dict[str, BadgeDef] = {b["id"]: b for b in BADGES}

RARITY_ORDER = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}
RARITY_EMOJI = {
    "common": "⚪",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}


def rarity_label(rarity: str) -> str:
    labels = {
        "common": "Обычный",
        "rare": "Редкий",
        "epic": "Эпический",
        "legendary": "Легендарный",
    }
    return labels.get(rarity, rarity)


def get_badge_progress(badge: dict, user: dict, stats: dict) -> str | None:
    """Возвращает строку прогресса для значка или None если бинарный."""
    progress = badge.get("progress")
    if not progress:
        return None
    label, key, target = progress
    # user поля берутся из user, stats — из stats
    current = user.get(key) if key in user else stats.get(key, 0)
    if current is None:
        current = 0
    current = int(current)
    remaining = max(0, target - current)
    pct = min(100, int(current / target * 100))
    bar = "▰" * (pct // 10) + "▱" * (10 - pct // 10)
    return f"{bar} {current}/{target} ({remaining} {label} осталось)"
