"""Клавиатуры бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from data.content import INTERESTS
from data.constants import EMOJI, MenuText, Photo
from data.enums import (
    CallbackPrefix,
    Gender,
    Seeking,
    SwipeAction,
    LikeResponse,
    PhotoAction,
    VerifyAction,
    AdminAction,
    BadgeAction,
    AnonAction,
    SettingsAction,
    EditField,
)

# Главное меню (reply-клавиатура)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=MenuText.SEARCH)],
        [KeyboardButton(text=MenuText.BLIND_DATE)],
        [KeyboardButton(text=MenuText.LIKES_INBOX), KeyboardButton(text=MenuText.MATCHES)],
        [KeyboardButton(text=MenuText.MY_PROFILE), KeyboardButton(text=MenuText.DAILY_QUESTION)],
        [KeyboardButton(text=MenuText.BADGES)],
        [KeyboardButton(text=MenuText.SETTINGS)],
    ],
    resize_keyboard=True,
)

# СВЁРНУТОЕ МЕНЮ — одна кнопка "Меню"
HIDE_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MenuText.MENU)]],
    resize_keyboard=True,
)

# Клавиатура внутри анонимного свидания — только выход
ANON_CHAT_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=MenuText.STOP_BLIND_DATE)]],
    resize_keyboard=True,
)


def anon_session_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.BLIND_DATE} Открыться", callback_data=CallbackPrefix.ANON.with_param(AnonAction.REVEAL.value))],
            [InlineKeyboardButton(text=f"{EMOJI.STOP} Завершить", callback_data=CallbackPrefix.ANON.with_param(AnonAction.STOP.value))],
        ]
    )


def anon_queue_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.STOP} Отменить поиск", callback_data=CallbackPrefix.ANON.with_param(AnonAction.CANCEL_QUEUE.value))]
        ]
    )


def gender_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{EMOJI.MALE} Парень", callback_data=f"{prefix}:{Gender.MALE.value}"),
                InlineKeyboardButton(text=f"{EMOJI.FEMALE} Девушка", callback_data=f"{prefix}:{Gender.FEMALE.value}"),
            ]
        ]
    )


def seeking_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{EMOJI.MALE} Парней", callback_data=f"{prefix}:{Seeking.MALE.value}"),
                InlineKeyboardButton(text=f"{EMOJI.FEMALE} Девушек", callback_data=f"{prefix}:{Seeking.FEMALE.value}"),
            ],
            [InlineKeyboardButton(text="🌈 Всех", callback_data=f"{prefix}:{Seeking.ANY.value}")],
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


def browse_kb(uid: int, has_extra_photos: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=EMOJI.LIKE, callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.LIKE.value, uid)),
            InlineKeyboardButton(text=EMOJI.MESSAGE_LIKE, callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.MESSAGE_LIKE.value, uid)),
            InlineKeyboardButton(text=EMOJI.DISLIKE, callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.DISLIKE.value, uid)),
        ],
    ]
    if has_extra_photos:
        rows.append([
            InlineKeyboardButton(text=f"{EMOJI.PHOTOS} Ещё фото", callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.PHOTOS.value, uid)),
        ])
    rows.append([
        InlineKeyboardButton(text=f"{EMOJI.REPORT} Пожаловаться", callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.REPORT.value, uid)),
        InlineKeyboardButton(text=f"{EMOJI.STOP} Стоп", callback_data=CallbackPrefix.SWIPE.with_param(SwipeAction.STOP.value, 0)),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def like_response_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{EMOJI.LIKE} Лайкнуть в ответ", callback_data=CallbackPrefix.LIKE.with_param(LikeResponse.YES.value, uid)),
                InlineKeyboardButton(text=f"{EMOJI.DISLIKE} Пропустить", callback_data=CallbackPrefix.LIKE.with_param(LikeResponse.NO.value, uid)),
            ]
        ]
    )


def profile_kb(has_daily: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✏️ Имя", callback_data=CallbackPrefix.EDIT.with_param(EditField.NAME.value)),
            InlineKeyboardButton(text="🎂 Возраст", callback_data=CallbackPrefix.EDIT.with_param(EditField.AGE.value)),
        ],
        [
            InlineKeyboardButton(text=f"{EMOJI.LOCATION} Город", callback_data=CallbackPrefix.EDIT.with_param(EditField.CITY.value)),
            InlineKeyboardButton(text=f"{EMOJI.BIO} О себе", callback_data=CallbackPrefix.EDIT.with_param(EditField.BIO.value)),
        ],
        [
            InlineKeyboardButton(text=f"{EMOJI.INTERESTS} Интересы", callback_data=CallbackPrefix.EDIT.with_param(EditField.INTERESTS.value)),
            InlineKeyboardButton(text="🖼 Фото", callback_data=CallbackPrefix.EDIT.with_param(EditField.PHOTOS.value)),
        ],
    ]
    if has_daily:
        rows.append([InlineKeyboardButton(text=f"{EMOJI.DELETE} Удалить ответ дня", callback_data=CallbackPrefix.EDIT.with_param(EditField.DELETE_DAILY.value))])
    rows.append([InlineKeyboardButton(text=f"{EMOJI.VERIFIED} Верификация", callback_data=CallbackPrefix.EDIT.with_param(EditField.VERIFY.value))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photos_manage_kb(photo_count: int, max_photos: int = Photo.MAX_TOTAL) -> InlineKeyboardMarkup:
    """Клавиатура управления фотогалереей."""
    rows = []
    if photo_count < max_photos:
        rows.append([InlineKeyboardButton(text=f"{EMOJI.ADD} Добавить фото", callback_data=CallbackPrefix.PHOTO.with_param(PhotoAction.ADD.value))])
    if photo_count > 1:
        btns = []
        for i in range(photo_count):
            btns.append(InlineKeyboardButton(text=f"{EMOJI.DELETE} {i+1}", callback_data=CallbackPrefix.PHOTO.with_param(PhotoAction.DELETE.value, i)))
        rows.append(btns)
    rows.append([InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.PHOTO.with_param(PhotoAction.BACK.value))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extra_photos_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.SKIP} Пропустить", callback_data=CallbackPrefix.REG_PHOTO.with_param("skip"))],
        ]
    )


def verify_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{EMOJI.VERIFIED} Одобрить", callback_data=CallbackPrefix.VERIFY.with_param(VerifyAction.APPROVE.value, tg_id)),
                InlineKeyboardButton(text=f"{EMOJI.DISLIKE} Отклонить", callback_data=CallbackPrefix.VERIFY.with_param(VerifyAction.REJECT.value, tg_id)),
            ]
        ]
    )


def settings_kb(active: bool) -> InlineKeyboardMarkup:
    toggle = f"{EMOJI.ACTIVE} Анкета активна (скрыть)" if active else f"{EMOJI.INACTIVE} Анкета скрыта (показать)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle, callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.TOGGLE.value))],
            [InlineKeyboardButton(text="🎚 Фильтр по возрасту", callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.AGE_FILTER.value))],
            [InlineKeyboardButton(text="👁 Кого показывать", callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.SEEKING.value))],
            [InlineKeyboardButton(text=f"{EMOJI.SUPPORT} Поддержка", callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.SUPPORT.value))],
            [InlineKeyboardButton(text=f"{EMOJI.DELETE} Удалить аккаунт", callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.DELETE.value))],
        ]
    )


def confirm_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{EMOJI.REPORT} Да, удалить всё",
                    callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.DELETE_CONFIRM.value),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{EMOJI.BACK} Отмена",
                    callback_data=CallbackPrefix.SETTINGS.with_param(SettingsAction.DELETE_CANCEL.value),
                ),
            ],
        ]
    )


def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🧧 Жалоба на пользователя",
                callback_data=CallbackPrefix.SUPPORT.with_param("report"),
            )],
            [InlineKeyboardButton(
                text="🗣 Нарушение моих прав",
                callback_data=CallbackPrefix.SUPPORT.with_param("rights"),
            )],
            [InlineKeyboardButton(
                text="❓ Другое",
                callback_data=CallbackPrefix.SUPPORT.with_param("other"),
            )],
        ]
    )


def support_reply_kb(tg_id: int, ticket_id: int | None = None) -> InlineKeyboardMarkup:
    cb = CallbackPrefix.SUPPORT_REPLY.with_param(tg_id, ticket_id) if ticket_id else CallbackPrefix.SUPPORT_REPLY.with_param(tg_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{EMOJI.MESSAGE_LIKE} Ответить",
                callback_data=cb,
            )],
        ]
    )


# ===== КЛАВИАТУРЫ ДЛЯ АРТЕФАКТОВ =====

def badges_kb(total: int) -> InlineKeyboardMarkup:
    """Клавиатура раздела Артефакты — БЕЗ кнопки "В меню"."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Прогресс", callback_data=CallbackPrefix.BADGE.with_param(BadgeAction.PROGRESS.value))],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=CallbackPrefix.BADGE.with_param(BadgeAction.COLLECTION.value))],
        ]
    )


def badge_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.BACK} Назад к коллекции", callback_data=CallbackPrefix.BADGE.with_param(BadgeAction.COLLECTION.value))],
        ]
    )


# ===== АДМИН-ПАНЕЛЬ =====

def admin_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню админ-панели."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.STATS.value))],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.USERS.value))],
            [InlineKeyboardButton(text="🚩 Жалобы", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.REPORTS.value))],
            [InlineKeyboardButton(text=f"{EMOJI.VERIFIED} Верификация", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.VERIFIED.value))],
            [InlineKeyboardButton(text=f"{EMOJI.BADGE_TROPHY} Артефакты", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.BADGES.value))],
            [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.BAN.value))],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.BROADCAST.value))],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад» в главное меню админ-панели."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.MENU.value))],
        ]
    )
