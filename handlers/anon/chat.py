"""Пересылка сообщений и открытие анкет в анонимном чате.

FIX: InAnonChat теперь сохраняет partner_id в event-data, чтобы relay()
     не делал повторный запрос anon_active_partner() — убрана двойная нагрузка
     на БД при каждом сообщении в анонимном чате.
FIX: добавлено логирование ошибок доставки.
FIX v8: copy_message → ручная пересылка по типам контента (безопасность).
        Вместо copy_message, который копирует всё как есть (включая caption,
        reply_markup и пр.), используем явную отправку по типу контента.
        Это предотвращает утечку метаданных и потенциальные проблемы безопасности.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.anon_repo as anon_repo
import repositories.like_repo as like_repo
import repositories.user_repo as user_repo
from data.constants import Message as Msg
from data.enums import CallbackPrefix, AnonAction
from keyboards import MAIN_MENU, anon_session_kb
from services.anon_rate_limiter import check_rate_limit
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award, invalidate_award_cache
from services.notification import announce_match
from services.relationship_service import RelationshipService, add_message_event
import asyncio


log = logging.getLogger("iskra." + __name__.split(".")[-1])

_background_tasks: set[asyncio.Task] = set()

router = Router()
log = logging.getLogger("iskra.anon")


class InAnonChat(BaseFilter):
    """Срабатывает только если пользователь в активной анонимной сессии.

    FIX: сохраняет partner_id в словарь event-data, чтобы хендлер relay()
    мог получить его без повторного запроса к БД.
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool | dict:
        partner = await anon_repo.anon_active_partner(event.from_user.id)
        if partner is None:
            return False
        # Передаём partner_id в хендлер через возвращаемый словарь
        return {"anon_partner_id": partner}


@router.callback_query(F.data == f"{CallbackPrefix.ANON.value}:{AnonAction.REVEAL.value}")
async def reveal(call: CallbackQuery, bot: Bot) -> None:
    """Обработчик открытия анкеты."""
    s = await anon_repo.anon_set_reveal(call.from_user.id)
    await call.answer()
    if s is None:
        await call.message.answer("Свидание уже завершено.", reply_markup=MAIN_MENU)
        return

    # Значок revealer (раскрылся в ≥10 свиданиях).
    for badge in await check_and_award(call.from_user.id):
        await call.message.answer(format_badge_card(badge, is_new=True))

    partner = s["b_id"] if s["a_id"] == call.from_user.id else s["a_id"]
    both_revealed = s["a_reveal"] and s["b_reveal"]

    if both_revealed:
        await _handle_both_revealed(bot, s)
    else:
        await call.message.answer(Msg.BLIND_DATE_REVEAL_WAIT)
        try:
            await bot.send_message(
                partner,
                Msg.BLIND_DATE_REVEAL_REQUEST,
                reply_markup=anon_session_kb(),
            )
        except Exception as e:
            log.warning("Не удалось отправить запрос reveal → %d: %s", partner, e)


async def _handle_both_revealed(bot: Bot, session: dict) -> None:
    """Обрабатывает случай, когда оба открылись."""
    a_id, b_id = session["a_id"], session["b_id"]
    await like_repo.add_like(a_id, b_id, True)
    await like_repo.add_like(b_id, a_id, True)
    await anon_repo.anon_end(a_id)
    await announce_match(bot, a_id, b_id)
    await RelationshipService.ensure_exists(a_id, b_id)

    for who in (a_id, b_id):
        try:
            await bot.send_message(
                who,
                Msg.BLIND_DATE_BOTH_REVEALED,
                reply_markup=MAIN_MENU,
            )
        except Exception as e:
            log.warning("Не удалось отправить both_revealed → %d: %s", who, e)


@router.message(InAnonChat())
async def relay(message: Message, bot: Bot, anon_partner_id: int) -> None:
    """Пересылает сообщения между собеседниками.

    FIX: partner_id передаётся из фильтра InAnonChat через keyword argument,
    вместо повторного запроса anon_active_partner() — убрана двойная нагрузка на БД.

    FIX v8: ручная пересылка по типам контента вместо copy_message.
    copy_message копирует ВСЕ метаданные, что потенциально небезопасно.
    """
    allowed, wait = check_rate_limit(message.from_user.id)
    if not allowed:
        await message.answer(Msg.RATE_LIMIT_WAIT.format(wait))
        return

    await user_repo.increment_anon_messages(message.from_user.id)
    try:
        await add_message_event(message.from_user.id, anon_partner_id)
    except Exception as e:
        log.debug("Failed to add message event: %s", e)

    # FIX v8: ручная пересылка по типу контента вместо copy_message
    try:
        if message.text:
            await bot.send_message(anon_partner_id, message.text)
        elif message.photo:
            await bot.send_photo(
                anon_partner_id,
                photo=message.photo[-1].file_id,
                caption=message.caption or "",
            )
        elif message.voice:
            await bot.send_voice(
                anon_partner_id,
                voice=message.voice.file_id,
                caption=message.caption or "",
            )
        elif message.video:
            await bot.send_video(
                anon_partner_id,
                video=message.video.file_id,
                caption=message.caption or "",
            )
        elif message.video_note:
            await bot.send_video_note(
                anon_partner_id,
                video_note=message.video_note.file_id,
            )
        elif message.sticker:
            await bot.send_sticker(
                anon_partner_id,
                sticker=message.sticker.file_id,
            )
        elif message.document:
            await bot.send_document(
                anon_partner_id,
                document=message.document.file_id,
                caption=message.caption or "",
            )
        elif message.audio:
            await bot.send_audio(
                anon_partner_id,
                audio=message.audio.file_id,
                caption=message.caption or "",
            )
        elif message.animation:
            await bot.send_animation(
                anon_partner_id,
                animation=message.animation.file_id,
                caption=message.caption or "",
            )
        elif message.location:
            await bot.send_location(
                anon_partner_id,
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            )
        elif message.contact:
            await bot.send_contact(
                anon_partner_id,
                phone_number=message.contact.phone_number,
                first_name=message.contact.first_name,
                last_name=message.contact.last_name or "",
            )
        else:
            # Fallback для неподдерживаемых типов
            await bot.send_message(
                anon_partner_id,
                "[Получено неподдерживаемое сообщение]"
            )
    except TelegramRetryAfter as e:
        log.warning("Rate limit relaying message %d → %d: retry after %s",
                    message.from_user.id, anon_partner_id, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            # Retry with text fallback
            if message.text:
                await bot.send_message(anon_partner_id, message.text)
            else:
                await bot.send_message(anon_partner_id, "[Сообщение не доставлено — попробуйте позже]")
        except Exception as e2:
            log.error("Failed to retry relay %d → %d: %s",
                      message.from_user.id, anon_partner_id, e2)
            await message.answer(Msg.DELIVERY_FAILED)
    except TelegramForbiddenError:
        log.warning("User %d blocked bot, cannot relay from %d",
                    anon_partner_id, message.from_user.id)
        await message.answer(Msg.DELIVERY_FAILED)
    except Exception as e:
        log.error("Failed to relay message %d → %d: %s",
                  message.from_user.id, anon_partner_id, e)
        await message.answer(Msg.DELIVERY_FAILED)
