"""Создание тикетов поддержки — меню категорий, отправка.

FIX: добавлено логирование ошибок доставки тикетов админам.
FIX: используется safe_send из services.safe_send.
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.support_repo as support_repo
import repositories.user_repo as user_repo
from config import ADMIN_IDS
from data.constants import Length, EMOJI, MenuText, Message, Format
from data.enums import CallbackPrefix, SupportCategory, Command as Cmd
from keyboards import MAIN_MENU
from services.safe_send import safe_send
from services.validation import sanitize_ticket_text
from states import Support

router = Router()
log = logging.getLogger("iskra.support.ticket")


@router.message(Command(Cmd.SUPPORT.value[1:]))
@router.message(F.text == MenuText.SUPPORT)
async def cmd_support(message: Message, state: FSMContext) -> None:
    """Показывает меню поддержки."""
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SupportCategory.REPORT.display_name, callback_data=CallbackPrefix.SUPPORT.with_param(SupportCategory.REPORT.value))],
            [InlineKeyboardButton(text=SupportCategory.RIGHTS.display_name, callback_data=CallbackPrefix.SUPPORT.with_param(SupportCategory.RIGHTS.value))],
            [InlineKeyboardButton(text=SupportCategory.OTHER.display_name, callback_data=CallbackPrefix.SUPPORT.with_param(SupportCategory.OTHER.value))],
            [InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.SUPPORT.with_param("back"))],
        ]
    )
    await message.answer(f"{EMOJI.SUPPORT} <b>Поддержка</b>\nС чем у вас возникла проблема?", reply_markup=kb)


@router.callback_query(F.data == CallbackPrefix.SUPPORT.with_param("back"))
async def on_support_back(call: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Назад» из меню поддержки."""
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        log.debug("edit_reply_markup failed: %s", e)
    await safe_send(
        call.message.answer("Главное меню:", reply_markup=MAIN_MENU),
        log_prefix="support_back",
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.SUPPORT.value}:"))
async def on_support_category(call: CallbackQuery, state: FSMContext) -> None:
    """Обработчик выбора категории."""
    cat = call.data.split(":")[1]
    if cat not in (SupportCategory.REPORT.value, SupportCategory.RIGHTS.value, SupportCategory.OTHER.value):
        await call.answer("Неизвестная категория")
        return
    category = SupportCategory(cat)
    await state.update_data(support_cat=cat, support_label=category.display_name)
    await state.set_state(Support.message)
    await call.message.edit_text(
        f"{category.display_name}\n"
        "Опишите вашу проблему одним сообщением.\n"
        "Можете прикрепить скриншот 📷\n"
        f"Для отмены — {Cmd.CANCEL.value}"
    )
    await call.answer()


@router.message(Support.message, Command(Cmd.CANCEL.value[1:]))
async def support_cancel(message: Message, state: FSMContext) -> None:
    """Отмена обращения."""
    await state.clear()
    await message.answer(Message.TICKET_CANCELLED, reply_markup=MAIN_MENU)


@router.message(Support.message, F.text)
async def support_text(message: Message, state: FSMContext) -> None:
    """Обработка текстового тикета."""
    await _process_ticket(message, state, text=message.text.strip())


@router.message(Support.message, F.photo)
async def support_photo(message: Message, state: FSMContext) -> None:
    """Обработка тикета с фото."""
    await _process_ticket(
        message, state,
        text=message.caption.strip() if message.caption else "(фото без описания)",
        photo_id=message.photo[-1].file_id,
    )


@router.message(Support.message)
async def support_invalid(message: Message) -> None:
    """Неверный формат тикета."""
    await message.answer("Отправьте текст или фото с описанием проблемы.")


async def _process_ticket(
    message: Message, state: FSMContext,
    text: str, photo_id: str | None = None,
) -> None:
    """Создаёт тикет и отправляет админам."""
    data = await state.get_data()
    cat_label = data.get("support_label", "❓")
    cat_key = data.get("support_cat", SupportCategory.OTHER.value)
    await state.clear()

    # Валидация текста тикета
    clean_text = await sanitize_ticket_text(text)
    if clean_text is None:
        await message.answer("Текст содержит недопустимые символы.", reply_markup=MAIN_MENU)
        return

    try:
        user = await user_repo.get_user(message.from_user.id)
    except Exception as e:
        log.error("Failed to load user %d for ticket: %s", message.from_user.id, e)
        user = None

    name = user["name"] if user else "?"
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    uid = message.from_user.id

    try:
        ticket_id = await support_repo.create_ticket(uid, cat_key, clean_text, photo_id)
    except Exception as e:
        log.error("Failed to create ticket for %d: %s", uid, e)
        await message.answer("Не удалось создать обращение 😕", reply_markup=MAIN_MENU)
        return

    ticket_text = Format.TICKET_CAPTION.format(ticket_id, cat_label, name, username, uid, clean_text)

    from keyboards import support_reply_kb
    for admin_id in ADMIN_IDS:
        if photo_id:
            await safe_send(
                message.bot.send_photo(
                    admin_id, photo=photo_id, caption=ticket_text,
                    reply_markup=support_reply_kb(uid, ticket_id),
                ),
                log_prefix=f"ticket_{ticket_id}_admin_{admin_id}",
            )
        else:
            await safe_send(
                message.bot.send_message(
                    admin_id, text=ticket_text,
                    reply_markup=support_reply_kb(uid, ticket_id),
                ),
                log_prefix=f"ticket_{ticket_id}_admin_{admin_id}",
            )

    await message.answer(Message.TICKET_SENT, reply_markup=MAIN_MENU)
