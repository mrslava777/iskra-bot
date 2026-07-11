"""Ответы администраторов на тикеты поддержки.

FIX v8: логирование ошибок отправки ответов, safe_send.
FIX v9: админ может ответить не только текстом, но и фото / голосовым.
 Раньше ловился только F.text — фото/голос молча проваливались, а состояние
 admin_reply зависало. Теперь поддержаны text, photo (с подписью) и voice.
"""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.support_repo as support_repo
from config import ADMIN_IDS
from data.constants import Message, Format
from data.enums import CallbackPrefix, Command as Cmd
from services.safe_send import safe_send
from states import Support

router = Router()
log = logging.getLogger("iskra.support.reply")


@router.callback_query(F.data.startswith(f"{CallbackPrefix.SUPPORT_REPLY.value}:"))
async def on_admin_reply(call: CallbackQuery, state: FSMContext) -> None:
    """Админ начинает ответ на тикет."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Только для админов", show_alert=True)
        return
    parts = call.data.split(":")
    tg_id = int(parts[1])
    ticket_id = int(parts[2]) if len(parts) > 2 else None
    await state.update_data(reply_to_user=tg_id, reply_ticket_id=ticket_id)
    await state.set_state(Support.admin_reply)
    await safe_send(
        call.message.answer(
            Format.ADMIN_REPLY_PROMPT.format(tg_id) + "\n(можно текст, фото или голосовое)"
        ),
        log_prefix="admin_reply",
    )
    await call.answer()


@router.message(Support.admin_reply, Command(Cmd.CANCEL.value[1:]))
async def admin_reply_cancel(message: Message, state: FSMContext) -> None:
    """Отмена ответа админа."""
    await state.clear()
    await message.answer(Message.REPLY_CANCELLED)


async def _finish_reply(message: Message, state: FSMContext, tg_id: int, ticket_id, saved_text: str) -> None:
    """Пометить тикет отвеченным и подтвердить админу."""
    await state.clear()
    try:
        if ticket_id:
            await support_repo.reply_ticket(ticket_id, saved_text)
    except Exception as e:
        log.error("Failed to save reply for ticket #%s: %s", ticket_id, e)
    await message.answer(Format.REPLY_SENT.format(tg_id))


@router.message(Support.admin_reply, F.text)
async def admin_reply_text(message: Message, state: FSMContext) -> None:
    """Текстовый ответ админа."""
    data = await state.get_data()
    tg_id = data.get("reply_to_user")
    if not tg_id:
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")
    reply_text = message.text.strip()

    await safe_send(
        message.bot.send_message(tg_id, Format.SUPPORT_REPLY.format(reply_text)),
        log_prefix=f"reply_to_{tg_id}",
    )
    await _finish_reply(message, state, tg_id, ticket_id, reply_text)


@router.message(Support.admin_reply, F.photo)
async def admin_reply_photo(message: Message, state: FSMContext) -> None:
    """Ответ админа фотографией (с подписью или без)."""
    data = await state.get_data()
    tg_id = data.get("reply_to_user")
    if not tg_id:
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")
    caption = message.caption.strip() if message.caption else ""
    header = Format.SUPPORT_REPLY.format(caption) if caption else Format.SUPPORT_REPLY.format("").rstrip()

    await safe_send(
        message.bot.send_photo(tg_id, photo=message.photo[-1].file_id, caption=header),
        log_prefix=f"reply_photo_to_{tg_id}",
    )
    await _finish_reply(message, state, tg_id, ticket_id, caption or "(фото)")


@router.message(Support.admin_reply, F.voice)
async def admin_reply_voice(message: Message, state: FSMContext) -> None:
    """Ответ админа голосовым сообщением."""
    data = await state.get_data()
    tg_id = data.get("reply_to_user")
    if not tg_id:
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")

    await safe_send(
        message.bot.send_message(tg_id, Format.SUPPORT_REPLY.format("").rstrip()),
        log_prefix=f"reply_voice_hdr_{tg_id}",
    )
    await safe_send(
        message.bot.send_voice(tg_id, voice=message.voice.file_id),
        log_prefix=f"reply_voice_to_{tg_id}",
    )
    await _finish_reply(message, state, tg_id, ticket_id, "(голосовое)")


@router.message(Support.admin_reply)
async def admin_reply_invalid(message: Message) -> None:
    """Неподдерживаемый тип ответа."""
    await message.answer("Ответь текстом, фото или голосовым. Для отмены — /cancel.")
