"""Клавиатуры бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from data.content import INTERESTS

# Главное меню (reply-клавиатура)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Смотреть анкеты")],
        [KeyboardButton(text="🎭 Свидание вслепую")],
        [KeyboardButton(text="💌 Кто меня лайкнул"), KeyboardButton(text="💞 Мэтчи")],
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="🎯 Вопрос дня")],
        [KeyboardButton(text="⚙️ Настройки")],
    ],
    resize_keyboard=True,
)

# Клавиатура внутри анонимного свидания — только выход
ANON_CHAT_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⏹ Завершить свидание")]],
    resize_keyboard=True,
)


def anon_session_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎭 Открыться", callback_data="anon:reveal")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="anon:stop")],
        ]
    )


def anon_queue_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Отменить поиск", callback_data="anon:cancelq")]
        ]
    )


def gender_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨 Парень", callback_data=f"{prefix}:m"),
                InlineKeyboardButton(text="👩 Девушка", callback_data=f"{prefix}:f"),
            ]
        ]
    )


def seeking_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨 Парней", callback_data=f"{prefix}:m"),
                InlineKeyboardButton(text="👩 Девушек", callback_data=f"{prefix}:f"),
            ],
            [InlineKeyboardButton(text="🌈 Всех", callback_data=f"{prefix}:any")],
        ]
    )


def interests_kb(selected: list[int], prefix: str = "int") -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, name in enumerate(INTERESTS):
        mark = "✅ " if i in selected else ""
        row.append(
            InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"{prefix}:{i}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✔️ Готово", callback_data=f"{prefix}:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def browse_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️", callback_data=f"sw:like:{uid}"),
                InlineKeyboardButton(text="💬", callback_data=f"sw:msglike:{uid}"),
                InlineKeyboardButton(text="👎", callback_data=f"sw:dislike:{uid}"),
            ],
            [
                InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"sw:report:{uid}"),
                InlineKeyboardButton(text="⏹ Стоп", callback_data="sw:stop:0"),
            ],
        ]
    )


def like_response_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️ Лайкнуть в ответ", callback_data=f"lk:yes:{uid}"),
                InlineKeyboardButton(text="👎 Пропустить", callback_data=f"lk:no:{uid}"),
            ]
        ]
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Имя", callback_data="ed:name"),
                InlineKeyboardButton(text="🎂 Возраст", callback_data="ed:age"),
            ],
            [
                InlineKeyboardButton(text="📍 Город", callback_data="ed:city"),
                InlineKeyboardButton(text="📝 О себе", callback_data="ed:bio"),
            ],
            [
                InlineKeyboardButton(text="🏷 Интересы", callback_data="ed:interests"),
                InlineKeyboardButton(text="📷 Фото", callback_data="ed:photo"),
            ],
            [InlineKeyboardButton(text="🎯 Ответить на вопрос дня", callback_data="ed:daily")],
        ]
    )


def settings_kb(active: bool) -> InlineKeyboardMarkup:
    toggle = "🟢 Анкета активна (скрыть)" if active else "🔴 Анкета скрыта (показать)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data="set:toggle")],
            [InlineKeyboardButton(text="🎚 Фильтр по возрасту", callback_data="set:age")],
            [InlineKeyboardButton(text="👁 Кого показывать", callback_data="set:seeking")],
        ]
    )
