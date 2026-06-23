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


def browse_kb(uid: int, has_extra_photos: bool = False, night_mode: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура ленты анкет. night_mode=True — ночные эмодзи."""
    if night_mode:
        rows = [
            [
                InlineKeyboardButton(text="🌙 Лайк", callback_data=f"sw:like:{uid}"),
                InlineKeyboardButton(text="💫 С сообщением", callback_data=f"sw:msglike:{uid}"),
                InlineKeyboardButton(text="🌑 Пропустить", callback_data=f"sw:dislike:{uid}"),
            ],
        ]
        # В ночном режиме не показываем доп. фото
        rows.append([
            InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"sw:report:{uid}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data="sw:stop:0"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # Обычный дневной режим
    rows = [
        [
            InlineKeyboardButton(text="❤️", callback_data=f"sw:like:{uid}"),
            InlineKeyboardButton(text="💬", callback_data=f"sw:msglike:{uid}"),
            InlineKeyboardButton(text="👎", callback_data=f"sw:dislike:{uid}"),
        ],
    ]
    if has_extra_photos:
        rows.append([
            InlineKeyboardButton(text="📸 Ещё фото", callback_data=f"sw:photos:{uid}"),
        ])
    rows.append([
        InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"sw:report:{uid}"),
        InlineKeyboardButton(text="⏹ Стоп", callback_data="sw:stop:0"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def like_response_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️ Лайкнуть в ответ", callback_data=f"lk:yes:{uid}"),
                InlineKeyboardButton(text="👎 Пропустить", callback_data=f"lk:no:{uid}"),
            ]
        ]
    )


def profile_kb(has_daily: bool = False) -> InlineKeyboardMarkup:
    rows = [
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
            InlineKeyboardButton(text="🖼 Фото", callback_data="ed:photos"),
        ],
        [InlineKeyboardButton(text="🎯 Ответить на вопрос дня", callback_data="ed:daily")],
    ]
    if has_daily:
        rows.append([InlineKeyboardButton(text="🗑 Удалить ответ дня", callback_data="ed:del_daily")])
    rows.append([InlineKeyboardButton(text="✅ Верификация", callback_data="ed:verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photos_manage_kb(photo_count: int, max_photos: int = 5) -> InlineKeyboardMarkup:
    """Клавиатура управления фотогалереей."""
    rows = []
    if photo_count < max_photos:
        rows.append([InlineKeyboardButton(text="➕ Добавить фото", callback_data="ph:add")])
    if photo_count > 1:
        btns = []
        for i in range(photo_count):
            btns.append(InlineKeyboardButton(text=f"🗑 {i+1}", callback_data=f"ph:del:{i}"))
        rows.append(btns)
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="ph:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extra_photos_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="regph:skip")],
        ]
    )


def verify_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"vrf:approve:{tg_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"vrf:reject:{tg_id}"),
            ]
        ]
    )


def settings_kb(active: bool) -> InlineKeyboardMarkup:
    toggle = "🟢 Анкета активна (скрыть)" if active else "🔴 Анкета скрыта (показать)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data="set:toggle")],
            [InlineKeyboardButton(text="🎚 Фильтр по возрасту", callback_data="set:age")],
            [InlineKeyboardButton(text="👁 Кого показывать", callback_data="set:seeking")],
            [InlineKeyboardButton(text="📩 Поддержка", callback_data="set:support")],
            [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="set:delete")],
        ]
    )


def confirm_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ Да, удалить всё",
                    callback_data="set:delete_confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data="set:delete_cancel",
                ),
            ],
        ]
    )


def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🧧 Жалоба на пользователя",
                callback_data="sup:report",
            )],
            [InlineKeyboardButton(
                text="🗣 Нарушение моих прав",
                callback_data="sup:rights",
            )],
            [InlineKeyboardButton(
                text="❓ Другое",
                callback_data="sup:other",
            )],
        ]
    )


def support_reply_kb(tg_id: int, ticket_id: int | None = None) -> InlineKeyboardMarkup:
    cb = f"supreply:{tg_id}:{ticket_id}" if ticket_id else f"supreply:{tg_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Ответить",
                callback_data=cb,
            )],
        ]
    )
