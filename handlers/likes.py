"""Входящие симпатии — просмотр и ответ на лайки.

PERF: viewer загружается один раз и передаётся дальше.
PERF: call.answer — fire-and-forget.
PERF: badge check параллелизирован с загрузкой следующей анкеты.
"""
import asyncio

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.like_repo as like_repo
import repositories.user_repo as user_repo
from data.constants import MenuText, Message, Format
from data.enums import CallbackPrefix, LikeResponse
from keyboards import MAIN_MENU, HIDE_MENU, like_response_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.notification import announce_match
from services.profile_formatter import format_profile_async


log = logging.getLogger("iskra." + __name__.split(".")[-1])

async def _safe_send(coro, fallback=None):
    """Safe wrapper for Telegram send operations."""
    try:
        return await coro
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception:
            pass
    except TelegramForbiddenError:
        pass
    except Exception:
        if fallback:
            try:
                return await fallback
            except Exception:
                pass
    return None

router = Router()


@router.message(F.text == MenuText.LIKES_INBOX)
async def show_incoming(message: Message) -> None:
    """Показывает входящие лайки."""
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return
    rows = await like_repo.incoming_likes(message.from_user.id)
    if not rows:
        await message.answer(Message.NO_LIKES, reply_markup=HIDE_MENU)
        return
    try:
        await message.answer(Format.INCOMING_LIKES.format(len(rows)))
    except Exception:
        pass
    await _show_incoming(message, rows[0], user)


async def _show_incoming(message: Message, candidate: dict, viewer: dict) -> None:
    """Показывает одну входящую анкету."""
    caption = await format_profile_async(candidate, viewer=viewer, show_compat=True, show_badges=True)
    try:
        await message.answer_photo(
            photo=candidate["photo_id"],
            caption=caption,
            reply_markup=like_response_kb(candidate["tg_id"]),
        )
    except Exception:
        await message.answer(caption, reply_markup=like_response_kb(candidate["tg_id"]))


@router.callback_query(F.data.startswith(f"{CallbackPrefix.LIKE.value}:"))
async def on_like_back(call: CallbackQuery, bot: Bot) -> None:
    """Обработчик ответа на входящий лайк."""
    _, decision, uid = call.data.split(":")
    target_id = int(uid)
    viewer_id = call.from_user.id

    # FIX: await directly
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if decision == LikeResponse.YES.value:
        matched = await like_repo.add_like(viewer_id, target_id, True)
        if matched:
            # FIX: create_task for actual coroutine
            try:
                asyncio.create_task(announce_match(bot, viewer_id, target_id))
            except Exception:
                pass
            await call.answer(Message.MATCH_ACHIEVED)
        else:
            await call.answer(Message.LIKE_SENT)
    else:
        await like_repo.add_like(viewer_id, target_id, False)
        await call.answer(Message.DISLIKE_SENT)

    # Параллельно: значки + загрузка данных для следующей анкеты
    new_badges, user, rows = await asyncio.gather(
        check_and_award(viewer_id),
        user_repo.get_user(viewer_id),
        like_repo.incoming_likes(viewer_id),
    )
    for badge in new_badges:
        try:
            await call.message.answer(format_badge_card(badge, is_new=True))
        except Exception:
            pass

    if not rows:
        await call.message.answer("Это были все входящие симпатии ✨", reply_markup=HIDE_MENU)
        return
    await _show_incoming(call.message, rows[0], user)


@router.callback_query(F.data == "open_likes")
async def on_open_likes(call: CallbackQuery) -> None:
    """Обработчик кнопки из пуш-уведомления о лайке."""
    await call.answer()
    await show_incoming(call.message)
