"""Список мэтчей — просмотр взаимных лайков и контактов.

FIX: убрана дублирующая _format_profile_with_batch_badges — используется
     единый format_profile_async из profile_formatter.py.
     Значки подставляются через badges_map (batch-загрузка сохранена).
FIX: добавлен обработчик callback rel:<uid> — уровень отношений.
FIX v8: логирование ошибок вместо bare pass.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.match_repo as match_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message as Msg, Format
from data.enums import CallbackPrefix
from keyboards import MAIN_MENU, HIDE_MENU
from services.badge_formatter import format_user_badges_inline
from services.badge_service import get_user_badges_batch
from services.compatibility import common_interests, compatibility, compat_bar
from services.profile_formatter import format_profile_async
from services.relationship_service import get_relationship, format_status
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
log = logging.getLogger("iskra.matches")


@router.message(F.text == MenuText.MATCHES)
async def show_matches(message: Message) -> None:
    """Показывает список мэтчей.

    Оптимизация: batch-загрузка значков для всех мэтчей одним запросом
    вместо N+1 запросов get_user_badges() на каждого мэтча.
    """
    try:
        rows = await match_repo.get_matches(message.from_user.id)
    except Exception as e:
        log.error("Failed to load matches for %d: %s", message.from_user.id, e)
        await message.answer("Не удалось загрузить мэтчи 😕", reply_markup=HIDE_MENU)
        return

    if not rows:
        await message.answer(Msg.NO_MATCHES, reply_markup=HIDE_MENU)
        return

    try:
        viewer = await user_repo.get_user(message.from_user.id)
    except Exception as e:
        log.error("Failed to load viewer %d: %s", message.from_user.id, e)
        viewer = None

    # Batch-загрузка значков для всех мэтчей одним запросом
    try:
        match_ids = [r["tg_id"] for r in rows]
        badges_map = await get_user_badges_batch(match_ids)
    except Exception as e:
        log.error("Failed to load badges batch: %s", e)
        badges_map = {}

    await message.answer(Format.MATCH_COUNT.format(len(rows)))
    for r in rows:
        try:
            await _show_match(message, r, viewer, badges_map)
        except Exception as e:
            log.error("Failed to show match %d: %s", r.get("tg_id", "?"), e)
    await message.answer("Это все твои мэтчи ✨", reply_markup=HIDE_MENU)


async def _show_match(
    message: Message,
    match: dict,
    viewer: dict,
    badges_map: dict[int, list[dict]],
) -> None:
    """Показывает одного мэтча с кнопкой уровня отношений.

    FIX: использует format_profile_async вместо дублирующей локальной функции.
    Значки подставляются из batch-загруженного badges_map.
    """
    contact = _format_contact(match)

    try:
        caption = await format_profile_async(match, viewer=viewer, show_compat=True, show_badges=False)
    except Exception as e:
        log.error("Failed to format profile for match %d: %s", match.get("tg_id", "?"), e)
        caption = f"<b>{match.get('name', 'Unknown')}</b>"

    # Добавляем значки из batch-загрузки (без дополнительного запроса)
    match_badges = badges_map.get(match["tg_id"], [])
    badge_line = format_user_badges_inline(match_badges)
    if badge_line:
        # Вставляем строку значков после первой строки (имя)
        lines = caption.split("\n", 1)
        if len(lines) > 1:
            caption = lines[0] + "\n" + badge_line + "\n" + lines[1]
        else:
            caption = lines[0] + "\n" + badge_line

    caption += f"\n\n{EMOJI.MESSAGE_LIKE} Контакт: {contact}"

    rel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.COMPAT} Уровень отношений", callback_data=CallbackPrefix.RELATIONSHIP.with_param(match["tg_id"]))],
        ]
    )
    try:
        await message.answer_photo(photo=match["photo_id"], caption=caption, reply_markup=rel_kb)
    except Exception as e:
        log.warning("Failed to send match photo for %d: %s", match.get("tg_id", "?"), e)
        try:
            await message.answer(caption, reply_markup=rel_kb)
        except Exception as e2:
            log.error("Failed to send match text for %d: %s", match.get("tg_id", "?"), e2)


def _format_contact(user: dict) -> str:
    """Форматирует контакт пользователя."""
    if user.get("username"):
        return Format.CONTACT_USERNAME.format(user["username"])
    return Format.CONTACT_LINK.format(user["tg_id"], user["name"])


@router.callback_query(F.data.startswith(f"{CallbackPrefix.RELATIONSHIP.value}:"))
async def on_relationship(call: CallbackQuery) -> None:
    """Показывает уровень отношений с мэтчем."""
    parts = call.data.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        await call.answer("Ошибка")
        return
    target_id = int(parts[1])
    viewer_id = call.from_user.id

    try:
        rel_stats = await get_relationship(viewer_id, target_id)
        text = format_status(rel_stats, viewer_id)
        await call.answer(text, show_alert=True)
    except Exception as e:
        log.error("Failed to get relationship %d <-> %d: %s", viewer_id, target_id, e)
        await call.answer("Не удалось загрузить уровень отношений", show_alert=True)
