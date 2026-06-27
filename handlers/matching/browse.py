"""Лента анкет — показ кандидатов, свайпы, жалобы."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

import repositories.like_repo as like_repo
import repositories.photo_repo as photo_repo
import repositories.profile_repo as profile_repo
import repositories.settings_repo as settings_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message
from data.enums import CallbackPrefix, SwipeAction
from keyboards import MAIN_MENU, browse_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.notification import announce_match, notify_liked
from services.profile_formatter import format_profile_async

router = Router()


@router.message(F.text == MenuText.SEARCH)
async def start_browse(message: Message, state: FSMContext) -> None:
    """Начинает просмотр ленты анкет."""
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return
    await user_repo.touch_activity(message.from_user.id)
    await _show_next(message, message.from_user.id)


async def _show_next(message: Message, viewer_id: int) -> None:
    """Показывает следующую анкету в ленте."""
    viewer = await user_repo.get_user(viewer_id)
    cand = await profile_repo.next_candidate(viewer_id, viewer)
    if cand is None:
        await message.answer(Message.NO_MORE_PROFILES, reply_markup=MAIN_MENU)
        return
    await profile_repo.mark_shown(viewer_id, cand["tg_id"])

    caption = await format_profile_async(cand, viewer=viewer, show_compat=True, show_badges=True)
    extra = await photo_repo.photo_count(cand["tg_id"]) > 1
    kb = browse_kb(cand["tg_id"], has_extra_photos=extra)

    try:
        await message.answer_photo(photo=cand["photo_id"], caption=caption, reply_markup=kb)
    except Exception:
        await message.answer(caption, reply_markup=kb)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.SWIPE.value}:"))
async def on_swipe(call: CallbackQuery, bot: Bot) -> None:
    """Обработчик свайпов (лайк, дизлайк, жалоба, фото)."""
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == SwipeAction.STOP.value:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(Message.SEARCH_STOPPED, reply_markup=MAIN_MENU)
        await call.answer()
        return

    target_id = int(parts[2])
    await call.message.edit_reply_markup(reply_markup=None)

    if action == SwipeAction.PHOTOS.value:
        await _handle_photos(call, target_id)
        return

    if action == SwipeAction.REPORT.value:
        await _handle_report(call, viewer_id, target_id)
        return

    is_like = action in (SwipeAction.LIKE.value, SwipeAction.MESSAGE_LIKE.value)
    matched = await like_repo.add_like(viewer_id, target_id, is_like)

    if is_like:
        await notify_liked(bot, viewer_id, target_id, with_message=(action == SwipeAction.MESSAGE_LIKE.value))
    if matched:
        await announce_match(bot, viewer_id, target_id)

    await _check_badges(call, viewer_id)
    await call.answer(Message.LIKE_SENT if is_like else Message.DISLIKE_SENT)
    await _show_next(call.message, viewer_id)


async def _handle_photos(call: CallbackQuery, target_id: int) -> None:
    """Показывает дополнительные фото пользователя."""
    photos = await photo_repo.get_photos(target_id)
    extras = [p for p in photos if p["position"] > 0]
    if extras:
        media = [InputMediaPhoto(media=p["photo_id"]) for p in extras]
        try:
            await call.message.answer_media_group(media)
        except Exception:
            pass
    else:
        await call.answer("Нет дополнительных фото")
    await call.answer()


async def _handle_report(call: CallbackQuery, viewer_id: int, target_id: int) -> None:
    """Обрабатывает жалобу на пользователя."""
    await settings_repo.add_report(viewer_id, target_id)
    await _check_badges(call, viewer_id)
    await call.answer(Message.REPORT_SENT)
    await _show_next(call.message, viewer_id)


async def _check_badges(call: CallbackQuery, viewer_id: int) -> None:
    """Проверяет и показывает новые значки."""
    new_badges = await check_and_award(viewer_id)
    for badge in new_badges:
        await call.message.answer(format_badge_card(badge, is_new=True))
