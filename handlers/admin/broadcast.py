"""Рассылка сообщений всем активным пользователям.

FIX v9: рассылка переведена на services.safe_send.safe_send_many (там рабочий
 flood-ретрай — раньше локальная копия ловила TelegramRetryAfter общим except
 и теряла сообщение). Добавлено ПОДТВЕРЖДЕНИЕ перед отправкой: одна опечатка
 больше не разошлёт спам всей базе. Текст держим в FSM между шагом ввода и
 подтверждением.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import repositories.settings_repo as settings_repo
from config import BROADCAST_DELAY, BROADCAST_CONCURRENT
from data.constants import Message as Msg, Format, EMOJI
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin
from services.safe_send import safe_send, safe_send_many

log = logging.getLogger("iskra.admin.broadcast")

router = Router()


class Broadcast(StatesGroup):
    confirm = State()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BROADCAST.value}")
async def cb_broadcast_help(call: CallbackQuery) -> None:
    """Инструкция по рассылке."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    text = (
        "📣 Рассылка \n\n"
        "Отправь команду:\n"
        f" {Cmd.BROADCAST.value} Текст сообщения \n\n"
        "Перед отправкой попрошу подтверждение."
    )
    await safe_send(
        call.message.edit_text(text, reply_markup=back_kb()),
        log_prefix="broadcast_help",
    )
    await call.answer()


@router.message(Command(Cmd.BROADCAST.value[1:]))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Шаг 1: принимает текст и показывает подтверждение."""
    if not is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer(Format.BROADCAST_USAGE)

    try:
        total = len(await settings_repo.admin_all_active_ids())
    except Exception as e:
        log.error("Failed to count active users for broadcast: %s", e)
        total = 0

    await state.update_data(broadcast_text=text)
    await state.set_state(Broadcast.confirm)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{EMOJI.DONE} Отправить ({total})",
                callback_data=CallbackPrefix.ADMIN.with_param("bcast_go"),
            ),
            InlineKeyboardButton(
                text=f"{EMOJI.BACK} Отмена",
                callback_data=CallbackPrefix.ADMIN.with_param("bcast_cancel"),
            ),
        ],
    ])
    preview = text if len(text) <= 500 else text[:500] + "…"
    await message.answer(
        f"📣 Разослать это сообщение {total} пользователям?\n\n"
        f"───\n{preview}\n───",
        reply_markup=kb,
    )


@router.callback_query(Broadcast.confirm, F.data == CallbackPrefix.ADMIN.with_param("bcast_cancel"))
async def cb_broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """Отмена рассылки на шаге подтверждения."""
    await state.clear()
    try:
        await call.message.edit_text("📣 Рассылка отменена.")
    except Exception:
        pass
    await call.answer("Отменено")


@router.callback_query(Broadcast.confirm, F.data == CallbackPrefix.ADMIN.with_param("bcast_go"))
async def cb_broadcast_go(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг 2: подтверждено — рассылаем через safe_send_many (с flood-ретраем)."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)

    data = await state.get_data()
    text = data.get("broadcast_text")
    await state.clear()
    await call.answer()

    if not text:
        return await call.message.edit_text("📣 Текст рассылки потерян, начни заново.")

    try:
        all_users = await settings_repo.admin_all_active_ids()
    except Exception as e:
        log.error("Failed to load active users for broadcast: %s", e)
        return await call.message.edit_text("Не удалось загрузить список пользователей 😕")

    total = len(all_users)
    try:
        await call.message.edit_text(Format.BROADCAST_START.format(total))
    except Exception:
        pass

    body = f"{Format.BROADCAST_PREFIX}{text}"
    try:
        sent, failed = await safe_send_many(
            call.bot,
            all_users,
            body,
            delay=BROADCAST_DELAY,
            concurrent=BROADCAST_CONCURRENT,
        )
    except asyncio.CancelledError:
        log.warning("Рассылка прервана (shutdown)")
        raise
    except Exception as e:
        log.error("Broadcast failed: %s", e)
        return await call.message.answer("Ошибка рассылки 😕")

    log.info("Рассылка завершена: отправлено %d, ошибок %d из %d", sent, failed, total)
    await safe_send(
        call.message.answer(Format.BROADCAST_DONE.format(sent, failed)),
        log_prefix="broadcast_done",
    )
