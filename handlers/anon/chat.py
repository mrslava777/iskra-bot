"""Пересылка сообщений и открытие анкет в анонимном чате.

FIX: InAnonChat сохраняет partner_id в event-data (relay() не делает
 повторный запрос anon_active_partner()).
FIX v8: copy_message → ручная пересылка по типам контента (безопасность).
FIX (#5 транзакционность reveal): reveal() использует anon_repo.finalize_reveal(),
 которая атомарно ставит флаг, завершает сессию, создаёт лайки/мэтч/relationship.
 announce_match вызывается ровно один раз (по status="finalized"), даже если
 оба нажали «Открыться» одновременно.
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.anon_repo as anon_repo
import repositories.user_repo as user_repo
from data.constants import Message as Msg
from data.enums import CallbackPrefix, AnonAction
from keyboards import MAIN_MENU, anon_session_kb
from services.anon_rate_limiter import check_rate_limit
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.notification import announce_match
from services.relationship_service import add_message_event, get_milestone_message

router = Router()
log = logging.getLogger("iskra.anon")


class InAnonChat(BaseFilter):
    """Срабатывает только если пользователь в активной анонимной сессии.

    Сохраняет partner_id в event-data, чтобы relay() не делал повторный
    запрос к БД.
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool | dict:
        partner = await anon_repo.anon_active_partner(event.from_user.id)
        if partner is None:
            return False
        return {"anon_partner_id": partner}


@router.callback_query(F.data == f"{CallbackPrefix.ANON.value}:{AnonAction.REVEAL.value}")
async def reveal(call: CallbackQuery, bot: Bot) -> None:
    """Обработчик открытия анкеты (атомарная финализация)."""
    result = await anon_repo.finalize_reveal(call.from_user.id)
    await call.answer()

    status = result.get("status")

    if status == "no_session":
        await call.message.answer("Свидание уже завершено.", reply_markup=MAIN_MENU)
        return

    # Значок revealer (раскрылся в ≥10 свиданиях).
    for badge in await check_and_award(call.from_user.id):
        await call.message.answer(format_badge_card(badge, is_new=True))

    if status == "waiting":
        partner = result["partner"]
        await call.message.answer(Msg.BLIND_DATE_REVEAL_WAIT)
        try:
            await bot.send_message(
                partner,
                Msg.BLIND_DATE_REVEAL_REQUEST,
                reply_markup=anon_session_kb(),
            )
        except Exception as e:
            log.warning("Не удалось отправить запрос reveal → %d: %s", partner, e)
        return

    if status == "already_done":
        # Финализацию выполнил собеседник — не дублируем announce_match.
        log.info("Reveal already finalized by partner for user %d", call.from_user.id)
        return

    if status == "finalized":
        await _announce_both_revealed(bot, result["a_id"], result["b_id"])


async def _announce_both_revealed(bot: Bot, a_id: int, b_id: int) -> None:
    """Оповещает обоих о раскрытии. DB-часть уже сделана в finalize_reveal()."""
    try:
        await announce_match(bot, a_id, b_id)
    except Exception as e:
        log.warning("announce_match failed for %d/%d: %s", a_id, b_id, e)

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

    partner_id приходит из фильтра InAnonChat (без повторного запроса к БД).
    Ручная пересылка по типам контента вместо copy_message (безопасность).
    """
    allowed, wait = check_rate_limit(message.from_user.id)
    if not allowed:
        await message.answer(Msg.RATE_LIMIT_WAIT.format(wait))
        return

    await user_repo.increment_anon_messages(message.from_user.id)
    try:
        milestones = await add_message_event(message.from_user.id, anon_partner_id)
        # Отправляем уведомления о вехах обоим
        for m in milestones:
            msg = get_milestone_message(m)
            try:
                await bot.send_message(message.from_user.id, msg)
            except Exception:
                pass
            try:
                await bot.send_message(anon_partner_id, msg)
            except Exception:
                pass
    except Exception as e:
        log.debug("Failed to add message event: %s", e)

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
            await bot.send_message(
                anon_partner_id,
                "[Получено неподдерживаемое сообщение]",
            )
    except TelegramRetryAfter as e:
        log.warning("Rate limit relaying message %d → %d: retry after %s",
                    message.from_user.id, anon_partner_id, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
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
