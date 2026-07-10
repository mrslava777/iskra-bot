"""Лента анкет — показ кандидатов, свайпы, жалобы.

PERF v4/v5: fire-and-forget уведомления, batch-загрузка кандидата, ранний call.answer().
FIX v8: _background_tasks для всех fire-and-forget + логирование.

NEW (автоскрытие по жалобам): _handle_report теперь ДОЖИДАЕТСЯ add_report
 (нужен результат — сработал ли порог), и при auto_hidden шлёт алерт админам.
 Сама запись жалобы быстрая, поэтому ждать её не больно.
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
from config import ADMIN_IDS
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


def _spawn(coro) -> None:
    """Запускает fire-and-forget задачу с удержанием ссылки."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _fire_badges(tg_id: int, message: Message) -> None:
    """Fire-and-forget: проверяет значки и отправляет уведомления параллельно."""
    try:
        new_badges = await check_and_award(tg_id)
        if new_badges:
            await asyncio.gather(*[
                message.answer(format_badge_card(b, is_new=True))
                for b in new_badges
            ], return_exceptions=True)
    except Exception as e:
        log.error("Failed to fire badges for %d: %s", tg_id, e)


async def _safe_edit_markup(message: Message) -> None:
    """Fire-and-forget: убирает клавиатуру в фоне."""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        log.debug("Failed to edit reply markup: %s", e)


@router.message(F.text == MenuText.SEARCH)
async def start_browse(message: Message, state: FSMContext) -> None:
    """Начинает просмотр ленты анкет."""
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Msg.CREATE_PROFILE_FIRST)
        return
    try:
        await user_repo.touch_activity(message.from_user.id)
    except Exception as e:
        log.warning("Failed to touch activity for %d: %s", message.from_user.id, e)
    await _show_next(message, message.from_user.id, viewer=user)


async def _show_next(message: Message, viewer_id: int, viewer: dict | None = None) -> None:
    """Показывает следующую анкету в ленте (1 SQL-запрос на кандидата)."""
    if viewer is None:
        viewer = await user_repo.get_user(viewer_id)

    cand = await profile_repo.next_candidate_full(viewer_id, viewer)
    if cand is None:
        await message.answer(Msg.NO_MORE_PROFILES, reply_markup=HIDE_MENU)
        return

    pct = compatibility(viewer.get("interests"), cand.get("interests"))

    try:
        _spawn(user_repo.update_max_compat(viewer_id, pct))
    except Exception as e:
        log.warning("Failed to update max_compat for %d: %s", viewer_id, e)

    badge_ids = cand.get("badge_ids", [])
    badges = [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]

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
    """Обработчик свайпов (лайк, дизлайк, жалоба, фото)."""
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == SwipeAction.STOP.value:
        await call.answer()
        _spawn(_safe_edit_markup(call.message))
        await call.message.answer(Msg.SEARCH_STOPPED, reply_markup=HIDE_MENU)
        return

    target_id = int(parts[2])

    if action == SwipeAction.LIKE.value:
        await call.answer(Msg.LIKE_SENT)
    elif action == SwipeAction.DISLIKE.value:
        await call.answer(Msg.DISLIKE_SENT)
    elif action == SwipeAction.MESSAGE_LIKE.value:
        await call.answer(Msg.LIKE_SENT)
    else:
        await call.answer()

    _spawn(_safe_edit_markup(call.message))

    if action == SwipeAction.PHOTOS.value:
        await _handle_photos(call, target_id)
        return

    if action == SwipeAction.REPORT.value:
        await _handle_report(call, bot, viewer_id, target_id)
        return

    is_like = action in (SwipeAction.LIKE.value, SwipeAction.MESSAGE_LIKE.value)

    matched = await like_repo.add_like(viewer_id, target_id, is_like)

    if is_like:
        try:
            _spawn(notify_liked(bot, viewer_id, target_id,
                                with_message=(action == SwipeAction.MESSAGE_LIKE.value)))
        except Exception as e:
            log.error("Failed to notify liked %d -> %d: %s", viewer_id, target_id, e)
        if matched:
            try:
                _spawn(announce_match(bot, viewer_id, target_id))
            except Exception as e:
                log.error("Failed to announce match %d <-> %d: %s", viewer_id, target_id, e)

    try:
        _spawn(_fire_badges(viewer_id, call.message))
    except Exception as e:
        log.error("Failed to fire badges for %d: %s", viewer_id, e)

    viewer = await user_repo.get_user(viewer_id)
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


async def _handle_report(call: CallbackQuery, bot: Bot, viewer_id: int, target_id: int) -> None:
    """Обрабатывает жалобу. Применяет порог автоскрытия и алертит админов."""
    await call.answer(Msg.REPORT_SENT)

    result = {"unique_reporters": 0, "auto_hidden": False}
    try:
        result = await settings_repo.add_report(viewer_id, target_id)
    except Exception as e:
        log.error("Failed to add report %d -> %d: %s", viewer_id, target_id, e)

    if result.get("auto_hidden"):
        log.warning("User %d auto-hidden after %d unique reports",
                    target_id, result.get("unique_reporters"))
        _spawn(_alert_admins_auto_hidden(bot, target_id, result.get("unique_reporters", 0)))

    try:
        _spawn(_fire_badges(viewer_id, call.message))
    except Exception as e:
        log.error("Failed to fire badges after report for %d: %s", viewer_id, e)

    viewer = await user_repo.get_user(viewer_id)
    await _show_next(call.message, viewer_id, viewer=viewer)


async def _alert_admins_auto_hidden(bot: Bot, target_id: int, reporters: int) -> None:
    """Шлёт админам уведомление об авто-скрытой анкете (fire-and-forget)."""
    if not ADMIN_IDS:
        return
    try:
        user = await user_repo.get_user(target_id)
    except Exception:
        user = None
    name = (user or {}).get("name") or "—"
    username = (user or {}).get("username")
    handle = f"@{username}" if username else "(без username)"
    text = (
        f"{EMOJI.REPORT} Анкета авто-скрыта по жалобам\n\n"
        f"Пользователь: {name} {handle}\n"
        f"ID: {target_id}\n"
        f"Уникальных жалобщиков: {reporters}\n\n"
        f"Проверь и реши: разбан/бан. /unban {target_id} — вернуть в ленту."
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            log.debug("Failed to alert admin %d: %s", admin_id, e)
