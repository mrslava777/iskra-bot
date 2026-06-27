"""Пересылка сообщений и открытие анкет в анонимном чате."""
from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

import repositories.anon_repo as anon_repo
import repositories.like_repo as like_repo
import repositories.user_repo as user_repo
from data.constants import Message
from data.enums import CallbackPrefix, AnonAction
from keyboards import MAIN_MENU, anon_session_kb
from services.anon_rate_limiter import check_rate_limit
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.notification import announce_match
from services.relationship_service import RelationshipService, add_message_event

router = Router()


class InAnonChat(BaseFilter):
    """Срабатывает только если пользователь в активной анонимной сессии."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await anon_repo.anon_active_partner(event.from_user.id) is not None


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
        await call.message.answer(Message.BLIND_DATE_REVEAL_WAIT)
        try:
            await bot.send_message(
                partner,
                Message.BLIND_DATE_REVEAL_REQUEST,
                reply_markup=anon_session_kb(),
            )
        except Exception:
            pass


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
                Message.BLIND_DATE_BOTH_REVEALED,
                reply_markup=MAIN_MENU,
            )
        except Exception:
            pass


@router.message(InAnonChat())
async def relay(message: Message, bot: Bot) -> None:
    """Пересылает сообщения между собеседниками."""
    partner = await anon_repo.anon_active_partner(message.from_user.id)
    if partner is None:
        return

    allowed, wait = check_rate_limit(message.from_user.id)
    if not allowed:
        await message.answer(Message.RATE_LIMIT_WAIT.format(wait))
        return

    await user_repo.increment_anon_messages(message.from_user.id)
    try:
        await add_message_event(message.from_user.id, partner)
    except Exception:
        pass

    try:
        await bot.copy_message(
            chat_id=partner,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        await message.answer(Message.DELIVERY_FAILED)
