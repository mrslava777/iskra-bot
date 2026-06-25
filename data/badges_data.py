"""Система достижений (Артефакты) Искры.\n\nКаждый значок имеет:\n  - id: уникальный ключ\n  - name: название для пользователя\n  - description: описание как получить\n  - icon: emoji или текстовая иконка\n  - rarity: common / rare / epic / legendary\n  - condition: функция-проверка (user_row, stats) -> bool\n  - color: hex-цвет для оформления\n"""
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
    return (user.get("streak") or 0) >= 7


def _check_streak_30(user, stats):
    return (user.get("streak") or 0) >= 30


def _check_high_compat(user, stats):
    return stats.get("max_compat", 0) >= 95


def _check_revealer(user, stats):
    return stats.get("anon_reveals", 0) >= 10


def _check_chatter(user, stats):
    return stats.get("anon_messages", 0) >= 100


def _check_popular(user, stats):
    return (user.get("rating") or 0) >= 50


def _check_verified(user, stats):
    return bool(user.get("verified"))


def _check_profile_complete(user, stats):
    checks = [
        user.get("name"),
        user.get("age"),
        user.get("city"),
        user.get("bio"),
        user.get("interests"),
        user.get("daily_a"),
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
    },
    {
        "id": "profile_complete",
        "name": "Открытая книга",
        "description": "Заполни 5 из 6 полей анкеты",
        "icon": "📖",
        "rarity": "common",
        "condition": _check_profile_complete,
        "color": "#95a5a6",
    },
    {
        "id": "first_match",
        "name": "Первая Искра",
        "description": "Получи первый мэтч",
        "icon": "🔥",
        "rarity": "common",
        "condition": _check_first_match,
        "color": "#e67e22",
    },
    {
        "id": "reporter",
        "name": "Страж порядка",
        "description": "Отправь жалобу на нарушителя",
        "icon": "🛡️",
        "rarity": "common",
        "condition": _check_reporter,
        "color": "#95a5a6",
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
    },
    {
        "id": "ten_matches",
        "name": "Сердцеед",
        "description": "10 мэтчей",
        "icon": "💘",
        "rarity": "rare",
        "condition": _check_ten_matches,
        "color": "#e74c3c",
    },
    {
        "id": "icebreaker",
        "name": "Мастер знакомств",
        "description": "5 лайков с сообщением",
        "icon": "💬",
        "rarity": "rare",
        "condition": _check_icebreaker,
        "color": "#3498db",
    },
    {
        "id": "photographer",
        "name": "Фотограф",
        "description": "Загрузи 5 фото в анкету",
        "icon": "📸",
        "rarity": "rare",
        "condition": _check_photographer,
        "color": "#3498db",
    },
    {
        "id": "verified",
        "name": "Проверенный",
        "description": "Пройди верификацию профиля",
        "icon": "✅",
        "rarity": "rare",
        "condition": _check_verified,
        "color": "#2ecc71",
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
    },
    {
        "id": "high_compat",
        "name": "Идеальная Пара",
        "description": "Найди анкету с 95%+ совместимостью",
        "icon": "💎",
        "rarity": "epic",
        "condition": _check_high_compat,
        "color": "#9b59b6",
    },
    {
        "id": "revealer",
        "name": "Открывашка",
        "description": "10 раз открылся на свидании вслепую",
        "icon": "🎭",
        "rarity": "epic",
        "condition": _check_revealer,
        "color": "#9b59b6",
    },
    {
        "id": "chatter",
        "name": "Болтун",
        "description": "100 сообщений в анонимном чате",
        "icon": "🗣️",
        "rarity": "epic",
        "condition": _check_chatter,
        "color": "#9b59b6",
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
    },
    {
        "id": "fifty_matches",
        "name": "Король/Королева мэтчей",
        "description": "50 мэтчей",
        "icon": "🏆",
        "rarity": "legendary",
        "condition": _check_fifty_matches,
        "color": "#f1c40f",
    },
    {
        "id": "hundred_likes",
        "name": "Щедрая душа",
        "description": "Поставь 100 лайков",
        "icon": "💯",
        "rarity": "legendary",
        "condition": _check_hundred_likes,
        "color": "#f1c40f",
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
