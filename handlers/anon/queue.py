"""Очередь анонимного чата — поиск, отмена, подключение.

FIX: добавлено логирование ошибок доставки вместо silent pass.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.anon_repo as anon_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message
from data.enums import CallbackPrefix, AnonAction
from keyboards import ANON_CHAT_MENU, MAIN_MENU, HIDE_MENU, anon_queue_kb, anon_session_kb

router = Router()
log = logging.getLogger("iskra.anon.queue")

INTRO = Message.BLIND_DATE_INTRO


@router.message(F.text == MenuText.BLIND_DATE)
async def blind_date(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обработчик входа в анонимный чат."""
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return
    await state.clear()
    await user_repo.touch_activity(message.from_user.id)

    status, partner = await anon_repo.anon_find_or_queue(message.from_user.id)

    if status == "in_session":
        await message.answer(
            Message.ALREADY_IN_SESSION,
            reply_markup=ANON_CHAT_MENU,
        )
    elif status == "waiting":
        await message.answer(
            Message.ALREADY_SEARCHING,
            reply_markup=anon_queue_kb(),
        )
    elif status == "queued":
        await message.answer(INTRO)
        await message.answer(
            Message.BLIND_DATE_SEARCHING,
            reply_markup=anon_queue_kb(),
        )
        await message.answer("👆 Поиск собеседника", reply_markup=HIDE_MENU)
    elif status == "matched":
        await _notify_matched(bot, message.from_user.id)
        await _notify_matched(bot, partner)


async def _notify_matched(bot: Bot, uid: int) -> None:
    """Уведомляет пользователя о найденном собеседнике."""
    try:
        await bot.send_message(
            uid,
            Message.BLIND_DATE_FOUND,
            reply_markup=ANON_CHAT_MENU,
        )
        await bot.send_message(
            uid,
            Message.BLIND_DATE_REVEAL_PROMPT,
            reply_markup=anon_session_kb(),
        )
    except Exception as e:
        log.warning("Не удалось уведомить о мэтче → %d: %s", uid, e)


@router.message(F.text == MenuText.STOP_BLIND_DATE)
async def stop_btn(message: Message, bot: Bot) -> None:
    """Завершает свидание по кнопке."""
    await _end_session(message.from_user.id, bot, notifier=message)


@router.message(Command("stop"))
async def stop_cmd(message: Message, bot: Bot) -> None:
    """Завершает свидание по команде."""
    await _end_session(message.from_user.id, bot, notifier=message)


@router.callback_query(F.data == f"{CallbackPrefix.ANON.value}:{AnonAction.CANCEL_QUEUE.value}")
async def cancel_queue(call: CallbackQuery, bot: Bot) -> None:
    """Отменяет поиск собеседника."""
    await call.answer("Поиск отменён")
    await anon_repo.anon_leave_queue(call.from_user.id)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass  # edit_reply_markup fails if message was already modified — OK
    await call.message.answer("Поиск отменён. Возвращайся в меню.", reply_markup=MAIN_MENU)


@router.callback_query(F.data == f"{CallbackPrefix.ANON.value}:{AnonAction.STOP.value}")
async def stop_cb(call: CallbackQuery, bot: Bot) -> None:
    """Завершает свидание из callback."""
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass  # edit_reply_markup fails if message was already modified — OK
    await _end_session(call.from_user.id, bot)


async def _end_session(uid: int, bot: Bot, notifier: Message | None = None) -> None:
    """Завершает сессию или поиск."""
    was_in_queue = await anon_repo.anon_in_queue(uid)
    partner = await anon_repo.anon_end(uid)

    if partner is None:
        text = Message.SEARCH_CANCELLED if was_in_queue else Message.NOT_IN_SESSION
        if notifier is not None:
            await notifier.answer(text, reply_markup=MAIN_MENU)
        else:
            try:
                await bot.send_message(uid, text, reply_markup=MAIN_MENU)
            except Exception as e:
                log.warning("Не удалось отправить end_session → %d: %s", uid, e)
        return

    for who in (uid, partner):
        try:
            await bot.send_message(
                who,
                Message.BLIND_DATE_ENDED,
                reply_markup=MAIN_MENU,
            )
        except Exception as e:
            log.warning("Не удалось отправить blind_date_ended → %d: %s", who, e)
