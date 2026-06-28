"""Список мэтчей — просмотр взаимных лайков и контактов.

FIX: убрана дублирующая _format_profile_with_batch_badges — используется
     единый format_profile_async из profile_formatter.py.
     Значки подставляются через badges_map (batch-загрузка сохранена).
"""
import logging

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.match_repo as match_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message as Msg, Format
from data.enums import CallbackPrefix
from keyboards import MAIN_MENU, HIDE_MENU
from services.badge_formatter import format_user_badges_inline
from services.badge_service import get_user_badges_batch
from services.compatibility import common_interests, compatibility, compat_bar
from services.profile_formatter import format_profile_async

router = Router()
log = logging.getLogger("iskra.matches")


@router.message(F.text == MenuText.MATCHES)
async def show_matches(message: Message) -> None:
    """Показывает список мэтчей.

    Оптимизация: batch-загрузка значков для всех мэтчей одним запросом
    вместо N+1 запросов get_user_badges() на каждого мэтча.
    """
    rows = await match_repo.get_matches(message.from_user.id)
    if not rows:
        await message.answer(Msg.NO_MATCHES, reply_markup=HIDE_MENU)
        return
    viewer = await user_repo.get_user(message.from_user.id)

    # Batch-загрузка значков для всех мэтчей одним запросом
    match_ids = [r["tg_id"] for r in rows]
    badges_map = await get_user_badges_batch(match_ids)

    await message.answer(Format.MATCH_COUNT.format(len(rows)))
    for r in rows:
        await _show_match(message, r, viewer, badges_map)
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

    caption = await format_profile_async(match, viewer=viewer, show_compat=True, show_badges=False)

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
    except Exception:
        await message.answer(caption, reply_markup=rel_kb)


def _format_contact(user: dict) -> str:
    """Форматирует контакт пользователя."""
    if user.get("username"):
        return Format.CONTACT_USERNAME.format(user["username"])
    return Format.CONTACT_LINK.format(user["tg_id"], user["name"])
