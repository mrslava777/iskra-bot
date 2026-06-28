"""Лента анкет — показ кандидатов, свайпы, жалобы.

PERF: viewer передаётся в _show_next (не перезапрашивается из БД).
PERF: touch_activity запускается fire-and-forget (не блокирует ответ).
PERF: _show_next объединяет все независимые DB-операции в asyncio.gather.
PERF: badge check в on_swipe запускается параллельно с show_next.
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


@router.message(F.text == MenuText.SEARCH)
async def start_browse(message: Message, state: FSMContext) -> None:
    """Начинает просмотр ленты анкет."""
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Msg.CREATE_PROFILE_FIRST)
        return
    # touch_activity — fire-and-forget, не блокирует ответ пользователю
    asyncio.create_task(_safe_touch(message.from_user.id))
    await _show_next(message, message.from_user.id, viewer=user)


async def _safe_touch(tg_id: int) -> None:
    """Fire-and-forget touch_activity с перехватом ошибок."""
    try:
        await user_repo.touch_activity(tg_id)
    except Exception:
        pass


async def _show_next(message: Message, viewer_id: int, viewer: dict | None = None) -> None:
    """Показывает следующую анкету в ленте.

    PERF: viewer передаётся из вызывающего кода — экономит 1 DB-запрос.
    PERF: все независимые операции параллелизированы через asyncio.gather.
    """
    if viewer is None:
        viewer = await user_repo.get_user(viewer_id)
    cand = await profile_repo.next_candidate(viewer_id, viewer)
    if cand is None:
        await message.answer(Msg.NO_MORE_PROFILES, reply_markup=HIDE_MENU)
        return

    # Совместимость (синхронный, быстрый, кэшированный)
    pct = compatibility(viewer.get("interests"), cand.get("interests"))

    # Параллельно: mark_shown + update_max_compat + photo_count + format_profile
    _, _, n_photos, caption = await asyncio.gather(
        profile_repo.mark_shown(viewer_id, cand["tg_id"]),
        user_repo.update_max_compat(viewer_id, pct),
        photo_repo.photo_count(cand["tg_id"]),
        format_profile_async(cand, viewer=viewer, show_compat=True, show_badges=True),
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
    """Обработчик свайпов (лайк, дизлайк, жалоба, фото)."""
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == SwipeAction.STOP.value:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(Msg.SEARCH_STOPPED, reply_markup=HIDE_MENU)
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

    # Уведомления и значки — запускаем параллельно с подготовкой следующей анкеты
    tasks = []
    if is_like:
        tasks.append(notify_liked(bot, viewer_id, target_id, with_message=(action == SwipeAction.MESSAGE_LIKE.value)))
    if matched:
        tasks.append(announce_match(bot, viewer_id, target_id))
    tasks.append(check_and_award(viewer_id))

    # Загружаем viewer для следующей анкеты параллельно с уведомлениями
    viewer_task = user_repo.get_user(viewer_id)
    tasks.append(viewer_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Новые значки — предпоследний результат (check_and_award)
    badge_result = results[-2]
    if isinstance(badge_result, list):
        for badge in badge_result:
            await call.message.answer(format_badge_card(badge, is_new=True))

    await call.answer(Msg.LIKE_SENT if is_like else Msg.DISLIKE_SENT)

    # Viewer из параллельной загрузки
    viewer = results[-1] if not isinstance(results[-1], Exception) else None
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
    await call.answer()


async def _handle_report(call: CallbackQuery, viewer_id: int, target_id: int) -> None:
    """Обрабатывает жалобу на пользователя."""
    # Параллельно: жалоба + проверка значков + загрузка viewer
    _, new_badges, viewer = await asyncio.gather(
        settings_repo.add_report(viewer_id, target_id),
        check_and_award(viewer_id),
        user_repo.get_user(viewer_id),
    )
    for badge in new_badges:
        await call.message.answer(format_badge_card(badge, is_new=True))
    await call.answer(Msg.REPORT_SENT)
    await _show_next(call.message, viewer_id, viewer=viewer)
