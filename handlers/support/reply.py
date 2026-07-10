"""Ответы администраторов на тикеты поддержки.

FIX v8: логирование ошибок отправки ответов.
"""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.support_repo as support_repo
from config import ADMIN_IDS
from data.constants import Message, Format
from data.enums import CallbackPrefix, Command as Cmd
from states import Support
import asyncio


log = logging.getLogger("iskra." + __name__.split(".")[-1])

async def _safe_send(coro, fallback=None):
    """Safe wrapper for Telegram send operations."""
    try:
        return await coro
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception as e2:
            log.warning("Retry failed after TelegramRetryAfter: %s", e2)
    except TelegramForbiddenError:
        log.debug("User blocked bot, skipping send")
    except Exception as e:
        log.warning("Send failed: %s", e)
        if fallback:
            try:
                return await fallback
            except Exception as e2:
                log.warning("Fallback failed: %s", e2)
    return None

router = Router()


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
    try:
        await call.message.answer(Format.ADMIN_REPLY_PROMPT.format(tg_id))
    except Exception as e:
        log.error("Failed to send reply prompt to admin %d: %s", call.from_user.id, e)
    await call.answer()


@router.message(Support.admin_reply, Command(Cmd.CANCEL.value[1:]))
async def admin_reply_cancel(message: Message, state: FSMContext) -> None:
    """Отмена ответа админа."""
    await state.clear()
    await message.answer(Message.REPLY_CANCELLED)


@router.message(Support.admin_reply, F.text)
async def admin_reply_send(message: Message, state: FSMContext) -> None:
    """Отправляет ответ админа пользователю."""
    data = await state.get_data()
    tg_id = data.get("reply_to_user")
    if not tg_id:
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")
    reply_text = message.text.strip()
    await state.clear()

    try:
        await message.bot.send_message(
            tg_id,
            Format.SUPPORT_REPLY.format(reply_text),
        )
    except TelegramRetryAfter as e:
        log.warning("Rate limit sending reply to %d, retry after %s", tg_id, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await message.bot.send_message(
                tg_id,
                Format.SUPPORT_REPLY.format(reply_text),
            )
        except Exception as e2:
            log.error("Failed to retry reply to %d: %s", tg_id, e2)
            await message.answer(Format.REPLY_FAILED.format(e2))
            return
    except TelegramForbiddenError:
        log.warning("User %d blocked bot, cannot send reply", tg_id)
        await message.answer(f"❌ Пользователь {tg_id} заблокировал бота")
        return
    except Exception as e:
        log.error("Failed to send reply to %d: %s", tg_id, e)
        await message.answer(Format.REPLY_FAILED.format(e))
        return

    try:
        if ticket_id:
            await support_repo.reply_ticket(ticket_id, reply_text)
    except Exception as e:
        log.error("Failed to save reply for ticket #%d: %s", ticket_id, e)

    await message.answer(Format.REPLY_SENT.format(tg_id))
