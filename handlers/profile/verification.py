"""Верификация профиля через кружочек со случайным жестом.

FIX: добавлено логирование ошибок доставки уведомлений.
FIX v8: try/except при отправке video_note админам + логирование.
"""
import logging
import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.user_repo as user_repo
from config import ADMIN_IDS
from data.constants import EMOJI, Format, Message, Verification as Vrf
from data.enums import CallbackPrefix, VerifyAction
from keyboards import profile_kb, verify_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from states import Verify
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
log = logging.getLogger("iskra.verify")


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:verify")
async def on_request_verify(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает кружочек для верификации."""
    try:
        user = await user_repo.get_user(call.from_user.id)
        if user.get("verified"):
            await call.answer(f"{EMOJI.VERIFIED} Ты уже верифицирован!")
            return
    except Exception as e:
        log.error("Failed to check verification status for %d: %s", call.from_user.id, e)
        await call.answer("Ошибка 😕", show_alert=True)
        return

    gesture = random.choice(Vrf.GESTURES)
    await state.update_data(required_gesture=gesture)

    text = Format.VERIFICATION_REQUEST.format(gesture)
    # Отправляем новое сообщение — чтобы появилась клавиатура
    await call.message.answer(text)
    await state.set_state(Verify.video_note)
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:back")
async def on_verify_back(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад — возврат в профиль из верификации."""
    await state.clear()
    try:
        user = await user_repo.get_user(call.from_user.id)
        caption = await format_profile_async(user, show_compat=False, show_badges=True)
        try:
            await call.message.edit_text(caption, reply_markup=profile_kb())
        except Exception as e:
            log.debug("edit_text failed, using answer: %s", e)
            await call.message.answer(caption, reply_markup=profile_kb())
    except Exception as e:
        log.error("Failed to go back from verify for %d: %s", call.from_user.id, e)
    await call.answer()


@router.message(Verify.video_note, F.video_note)
async def on_verify_video_note(message: Message, state: FSMContext) -> None:
    """Принимает кружочек — push + меню."""
    video_note_id = message.video_note.file_id
    data = await state.get_data()
    gesture = data.get("required_gesture", "?")
    await state.clear()

    try:
        user = await user_repo.get_user(message.from_user.id)
        name = user["name"] if user else "?"
    except Exception as e:
        log.error("Failed to load user %d for verification: %s", message.from_user.id, e)
        name = "?"

    for admin_id in ADMIN_IDS:
        try:
            # FIX v8: try/except для каждого admin
            await message.bot.send_video_note(admin_id, video_note=video_note_id)
            await message.bot.send_message(
                admin_id,
                "🔍 <b>Запрос верификации</b>\n\n"
                "Пользователь: <b>" + name + "</b>\n"
                "ID: <code>" + str(message.from_user.id) + "</code>\n"
                "Требуемый жест: <b>" + gesture + "</b>\n\n"
                "Проверь, что жест виден в кадре и лицо совпадает с анкетой.",
                reply_markup=verify_kb(message.from_user.id),
            )
        except TelegramRetryAfter as e:
            log.warning("Rate limit sending verification to admin %d, retry after %s", admin_id, e.retry_after)
            await asyncio.sleep(e.retry_after)
            try:
                await message.bot.send_video_note(admin_id, video_note=video_note_id)
                await message.bot.send_message(
                    admin_id,
                    "🔍 <b>Запрос верификации</b>\n\n"
                    "Пользователь: <b>" + name + "</b>\n"
                    "ID: <code>" + str(message.from_user.id) + "</code>\n"
                    "Требуемый жест: <b>" + gesture + "</b>",
                    reply_markup=verify_kb(message.from_user.id),
                )
            except Exception as e2:
                log.error("Failed to retry verification to admin %d: %s", admin_id, e2)
        except TelegramForbiddenError:
            log.warning("Admin %d blocked bot, cannot send verification", admin_id)
        except Exception as e:
            log.error("Failed to send verification request to admin %d: %s", admin_id, e)

    await message.answer(Message.VERIFICATION_SENT, reply_markup=MAIN_MENU)


@router.message(Verify.video_note)
async def on_verify_invalid(message: Message) -> None:
    """Напоминает, что нужен именно кружочек."""
    await message.answer("🎥 Нужно записать <b>кружочек</b> (видеосообщение), а не фото или текст.")


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.APPROVE.value}:"))
async def on_approve_verify(call: CallbackQuery) -> None:
    """Админ одобряет верификацию — шлёт пуш пользователю."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    try:
        await user_repo.upsert_user(tg_id, verified=1)
    except Exception as e:
        log.error("Failed to approve verification for %d: %s", tg_id, e)
        await call.answer("Ошибка одобрения 😕", show_alert=True)
        return

    await call.answer(f"{EMOJI.VERIFIED} Верифицирован", show_alert=True)
    try:
        if call.message.photo:
            await call.message.edit_caption(
                caption=call.message.caption + "\n\n" + f"{EMOJI.VERIFIED} <b>Верифицирован</b>"
            )
        else:
            await call.message.edit_text(
                call.message.text + "\n\n" + f"{EMOJI.VERIFIED} <b>Верифицирован</b>"
            )
    except Exception as e:
        log.debug("Failed to edit verification status: %s", e)

    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_APPROVED)
    except TelegramRetryAfter as e:
        log.warning("Rate limit sending verification approval to %d, retry after %s", tg_id, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await call.bot.send_message(tg_id, Message.VERIFICATION_APPROVED)
        except Exception as e2:
            log.error("Failed to retry verification approval to %d: %s", tg_id, e2)
    except TelegramForbiddenError:
        log.debug("User %d blocked bot, cannot send verification approval", tg_id)
    except Exception as e:
        log.error("Failed to send verification approval to %d: %s", tg_id, e)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.REJECT.value}:"))
async def on_reject_verify(call: CallbackQuery) -> None:
    """Админ отклоняет верификацию — шлёт пуш пользователю."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    await call.answer(f"{EMOJI.DISLIKE} Отклонено", show_alert=True)
    try:
        if call.message.photo:
            await call.message.edit_caption(
                caption=call.message.caption + "\n\n" + f"{EMOJI.DISLIKE} <b>Отклонено</b>"
            )
        else:
            await call.message.edit_text(
                call.message.text + "\n\n" + f"{EMOJI.DISLIKE} <b>Отклонено</b>"
            )
    except Exception as e:
        log.debug("Failed to edit rejection status: %s", e)

    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_REJECTED)
    except TelegramRetryAfter as e:
        log.warning("Rate limit sending verification rejection to %d, retry after %s", tg_id, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await call.bot.send_message(tg_id, Message.VERIFICATION_REJECTED)
        except Exception as e2:
            log.error("Failed to retry verification rejection to %d: %s", tg_id, e2)
    except TelegramForbiddenError:
        log.debug("User %d blocked bot, cannot send verification rejection", tg_id)
    except Exception as e:
        log.error("Failed to send verification rejection to %d: %s", tg_id, e)
