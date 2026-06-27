"""Список мэтчей — просмотр взаимных лайков и контактов."""
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.match_repo as match_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message, Format
from data.enums import CallbackPrefix
from keyboards import MAIN_MENU, HIDE_MENU
from services.profile_formatter import format_profile_async

router = Router()


@router.message(F.text == MenuText.MATCHES)
async def show_matches(message: Message) -> None:
    """Показывает список мэтчей."""
    rows = await match_repo.get_matches(message.from_user.id)
    if not rows:
        await message.answer(Message.NO_MATCHES, reply_markup=HIDE_MENU)
        return
    viewer = await user_repo.get_user(message.from_user.id)
    await message.answer(Format.MATCH_COUNT.format(len(rows)))
    for r in rows:
        await _show_match(message, r, viewer)
    await message.answer("Это все твои мэтчи ✨", reply_markup=HIDE_MENU)


async def _show_match(message: Message, match: dict, viewer: dict) -> None:
    """Показывает одного мэтча с кнопкой уровня отношений."""
    contact = _format_contact(match)
    caption = await format_profile_async(match, viewer=viewer, show_compat=True, show_badges=True)
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
