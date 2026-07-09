"""Лента анкет — показ кандидатов, свайпы, жалобы.

PERF v4: notify_liked/announce_match — fire-and-forget (viewer не ждёт чужие уведомления).
PERF v4: update_max_compat — fire-and-forget (не влияет на отображение).
PERF v4: check_and_award — fire-and-forget с авто-отправкой значков.
PERF v5: next_candidate_full — batch-загружает photo_count + badge_ids в 1 запросе.
PERF v5: call.answer() ДО edit_reply_markup — убирает воспринимаемую задержку.
PERF v5: badges отправляются параллельно.
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

import repositories.like_repo as like_repo
import repositories.profile_repo as profile_repo
import repositories.settings_repo as settings_repo
import repositories.user_repo as user_repo
from badges import BADGE_BY_ID
from data.constants import EMOJI, MenuText, Message as Msg
from data.enums import CallbackPrefix, SwipeAction
from keyboards import MAIN_MENU, HIDE_MENU, browse_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.compatibility import compatibility
from services.notification import announce_match, notify_liked
from services.profile_formatter import format_profile_async

_background_tasks: set[asyncio.Task] = set()
router = Router()
log = logging.getLogger("iskra.browse")


async def _fire_badges(tg_id: int, message: Message) -> None:
    """Fire-and-forget: проверяет значки и отправляет уведомления параллельно."""
    try:
        new_badges = await check_and_award(tg_id)
        if new_badges:
            # FIX v5: отправляем значки параллельно, а не последовательно
            await asyncio.gather(*[
                message.answer(format_badge_card(b, is_new=True))
                for b in new_badges
            ], return_exceptions=True)
    except Exception:
        pass


async def _safe_edit_markup(message: Message) -> None:
    """Fire-and-forget: убирает клавиатуру в фоне."""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.message(F.text == MenuText.SEARCH)
async def start_browse(message: Message, state: FSMContext) -> None:
    """Начинает просмотр ленты анкет."""
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Msg.CREATE_PROFILE_FIRST)
        return
    # FIX: await touch_activity directly
    try:
        await user_repo.touch_activity(message.from_user.id)
    except Exception:
        pass
    await _show_next(message, message.from_user.id, viewer=user)


async def _show_next(message: Message, viewer_id: int, viewer: dict | None = None) -> None:
    """Показывает следующую анкету в ленте.

    PERF v5: next_candidate_full — 1 SQL-запрос вместо 3.
    Было: next_candidate_and_mark + photo_count + get_user_badges = 3 запроса.
    Стало: next_candidate_full = 1 запрос (с photo_count + badge_ids в CTE).
    """
    if viewer is None:
        viewer = await user_repo.get_user(viewer_id)

    # FIX v5: batch-загружаем всё за 1 запрос
    cand = await profile_repo.next_candidate_full(viewer_id, viewer)
    if cand is None:
        await message.answer(Msg.NO_MORE_PROFILES, reply_markup=HIDE_MENU)
        return

    # Совместимость (синхронный, кэшированный — мгновенно)
    pct = compatibility(viewer.get("interests"), cand.get("interests"))

    # update_max_compat — fire-and-forget (не критично для ответа)
    try:
        _task = asyncio.create_task(user_repo.update_max_compat(viewer_id, pct))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
    except Exception:
        pass

    # FIX v5: значки из batch-загрузки, не делаем лишний запрос
    badge_ids = cand.get("badge_ids", [])
    badges = [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]

    # Только format_profile_async — photo_count уже в cand
    caption = await format_profile_async(
        cand, viewer=viewer, show_compat=True, show_badges=True, badges=badges
    )
    n_photos = cand.get("photo_count", 0)

    extra = n_photos > 1
    kb = browse_kb(cand["tg_id"], has_extra_photos=extra)

    try:
        await message.answer_photo(photo=cand["photo_id"], caption=caption, reply_markup=kb)
    except Exception as e:
        log.debug("Не удалось отправить фото кандидата %d: %s", cand["tg_id"], e)
        await message.answer(caption, reply_markup=kb)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.SWIPE.value}:"))
async def on_swipe(call: CallbackQuery, bot: Bot) -> None:
    """Обработчик свайпов (лайк, дизлайк, жалоба, фото).

    PERF v5: call.answer() — ПЕРВЫМ, мгновенная обратная связь.
    edit_reply_markup — fire-and-forget в фоне.
    """
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == SwipeAction.STOP.value:
        # FIX v5: answer первым — мгновенная реакция
        await call.answer()
        _task = asyncio.create_task(_safe_edit_markup(call.message))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
        await call.message.answer(Msg.SEARCH_STOPPED, reply_markup=HIDE_MENU)
        return

    target_id = int(parts[2])

    # FIX v5: answer первым, edit — в фоне
    if action == SwipeAction.LIKE.value:
        await call.answer(Msg.LIKE_SENT)
    elif action == SwipeAction.DISLIKE.value:
        await call.answer(Msg.DISLIKE_SENT)
    elif action == SwipeAction.MESSAGE_LIKE.value:
        await call.answer(Msg.LIKE_SENT)
    else:
        await call.answer()

    _task = asyncio.create_task(_safe_edit_markup(call.message))
    _background_tasks.add(_task)
    _task.add_done_callback(_background_tasks.discard)

    if action == SwipeAction.PHOTOS.value:
        await _handle_photos(call, target_id)
        return

    if action == SwipeAction.REPORT.value:
        await _handle_report(call, viewer_id, target_id)
        return

    is_like = action in (SwipeAction.LIKE.value, SwipeAction.MESSAGE_LIKE.value)

    # add_like — нужен результат (matched?)
    matched = await like_repo.add_like(viewer_id, target_id, is_like)

    # === Все фоновые операции — fire-and-forget ===
    if is_like:
        try:
            _task = asyncio.create_task(notify_liked(bot, viewer_id, target_id, with_message=(action == SwipeAction.MESSAGE_LIKE.value)))
            _background_tasks.add(_task)
            _task.add_done_callback(_background_tasks.discard)
        except Exception:
            pass
    if matched:
        try:
            _task = asyncio.create_task(announce_match(bot, viewer_id, target_id))
            _background_tasks.add(_task)
            _task.add_done_callback(_background_tasks.discard)
        except Exception:
            pass

    # Значки — fire-and-forget с авто-отправкой
    try:
        _task = asyncio.create_task(_fire_badges(viewer_id, call.message))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
    except Exception:
        pass

    # === Единственное блокирующее: показать следующую карточку ===
    viewer = await user_repo.get_user(viewer_id)  # cached — мгновенно
    await _show_next(call.message, viewer_id, viewer=viewer)


async def _handle_photos(call: CallbackQuery, target_id: int) -> None:
    """Показывает дополнительные фото пользователя."""
    from repositories.photo_repo import get_photos
    photos = await get_photos(target_id)
    extras = [p for p in photos if p["position"] > 0]
    if extras:
        media = [InputMediaPhoto(media=p["photo_id"]) for p in extras]
        try:
            await call.message.answer_media_group(media)
        except Exception as e:
            log.debug("Не удалось отправить доп. фото %d: %s", target_id, e)
    else:
        await call.answer("Нет дополнительных фото")


async def _handle_report(call: CallbackQuery, viewer_id: int, target_id: int) -> None:
    """Обрабатывает жалобу на пользователя."""
    await call.answer(Msg.REPORT_SENT)
    try:
        _task = asyncio.create_task(settings_repo.add_report(viewer_id, target_id))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
    except Exception:
        pass
    try:
        _task = asyncio.create_task(_fire_badges(viewer_id, call.message))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)
    except Exception:
        pass
    viewer = await user_repo.get_user(viewer_id)  # cached
    await _show_next(call.message, viewer_id, viewer=viewer)
