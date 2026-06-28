"""Лента анкет — показ кандидатов, свайпы, жалобы.

PERF v4: notify_liked/announce_match — fire-and-forget (viewer не ждёт чужие уведомления).
PERF v4: update_max_compat — fire-and-forget (не влияет на отображение).
PERF v4: check_and_award — fire-and-forget с авто-отправкой значков.
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

import repositories.like_repo as like_repo
import repositories.photo_repo as photo_repo
import repositories.profile_repo as profile_repo
import repositories.settings_repo as settings_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message as Msg
from data.enums import CallbackPrefix, SwipeAction
from keyboards import MAIN_MENU, HIDE_MENU, browse_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award
from services.compatibility import compatibility
from services.notification import announce_match, notify_liked
from services.profile_formatter import format_profile_async

router = Router()
log = logging.getLogger("iskra.browse")


from services.async_utils import fire as _fire  # noqa: E302


async def _fire_badges(tg_id: int, message: Message) -> None:
    """Fire-and-forget: проверяет значки и отправляет уведомления."""
    try:
        new_badges = await check_and_award(tg_id)
        for badge in new_badges:
            await message.answer(format_badge_card(badge, is_new=True))
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
    _fire(user_repo.touch_activity(message.from_user.id))
    await _show_next(message, message.from_user.id, viewer=user)


async def _show_next(message: Message, viewer_id: int, viewer: dict | None = None) -> None:
    """Показывает следующую анкету в ленте.

    PERF: CTE объединяет next_candidate + mark_shown в 1 SQL-запрос.
    PERF: update_max_compat — fire-and-forget (не влияет на отображение).
    PERF: format + photo_count — единственный блокирующий gather.
    """
    if viewer is None:
        viewer = await user_repo.get_user(viewer_id)

    # CTE: находим кандидата И отмечаем как показанного — 1 запрос вместо 2
    cand = await profile_repo.next_candidate_and_mark(viewer_id, viewer)
    if cand is None:
        await message.answer(Msg.NO_MORE_PROFILES, reply_markup=HIDE_MENU)
        return

    # Совместимость (синхронный, кэшированный — мгновенно)
    pct = compatibility(viewer.get("interests"), cand.get("interests"))

    # update_max_compat — fire-and-forget (не критично для ответа)
    _fire(user_repo.update_max_compat(viewer_id, pct))

    # Параллельно: format + photo_count (оба нужны для ответа)
    caption, n_photos = await asyncio.gather(
        format_profile_async(cand, viewer=viewer, show_compat=True, show_badges=True),
        photo_repo.photo_count(cand["tg_id"]),
    )

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

    PERF v4: notify_liked и announce_match — fire-and-forget.
    Viewer не должен ждать доставку уведомлений другому пользователю.
    Экономия: ~200-400мс на каждый лайк-свайп.
    """
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == SwipeAction.STOP.value:
        _fire(call.message.edit_reply_markup(reply_markup=None))
        await call.message.answer(Msg.SEARCH_STOPPED, reply_markup=HIDE_MENU)
        _fire(call.answer())
        return

    target_id = int(parts[2])

    # Fire-and-forget: убираем кнопки со старой карточки
    _fire(call.message.edit_reply_markup(reply_markup=None))

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
    # Viewer не ждёт доставку уведомлений и проверку значков
    _fire(call.answer(Msg.LIKE_SENT if is_like else Msg.DISLIKE_SENT))

    if is_like:
        _fire(notify_liked(bot, viewer_id, target_id, with_message=(action == SwipeAction.MESSAGE_LIKE.value)))
    if matched:
        _fire(announce_match(bot, viewer_id, target_id))

    # Значки — fire-and-forget с авто-отправкой
    _fire(_fire_badges(viewer_id, call.message))

    # === Единственное блокирующее: показать следующую карточку ===
    viewer = await user_repo.get_user(viewer_id)  # cached — мгновенно
    await _show_next(call.message, viewer_id, viewer=viewer)


async def _handle_photos(call: CallbackQuery, target_id: int) -> None:
    """Показывает дополнительные фото пользователя."""
    photos = await photo_repo.get_photos(target_id)
    extras = [p for p in photos if p["position"] > 0]
    if extras:
        media = [InputMediaPhoto(media=p["photo_id"]) for p in extras]
        try:
            await call.message.answer_media_group(media)
        except Exception as e:
            log.debug("Не удалось отправить доп. фото %d: %s", target_id, e)
    else:
        await call.answer("Нет дополнительных фото")
    _fire(call.answer())


async def _handle_report(call: CallbackQuery, viewer_id: int, target_id: int) -> None:
    """Обрабатывает жалобу на пользователя."""
    _fire(call.answer(Msg.REPORT_SENT))
    _fire(settings_repo.add_report(viewer_id, target_id))
    _fire(_fire_badges(viewer_id, call.message))
    viewer = await user_repo.get_user(viewer_id)  # cached
    await _show_next(call.message, viewer_id, viewer=viewer)
