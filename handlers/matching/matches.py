"""Список мэтчей — просмотр взаимных лайков и контактов."""
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.match_repo as match_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, MenuText, Message, Format
from data.enums import CallbackPrefix
from keyboards import MAIN_MENU, HIDE_MENU
from services.profile_formatter import format_profile_async
from services.badge_formatter import format_user_badges_inline_batch
from services.badge_service import get_user_badges_batch
from services.compatibility import common_interests, compatibility, compat_bar

router = Router()


@router.message(F.text == MenuText.MATCHES)
async def show_matches(message: Message) -> None:
    """Показывает список мэтчей.

    Оптимизация: batch-загрузка значков для всех мэтчей одним запросом
    вместо N+1 запросов get_user_badges() на каждого мэтча.
    """
    rows = await match_repo.get_matches(message.from_user.id)
    if not rows:
        await message.answer(Message.NO_MATCHES, reply_markup=HIDE_MENU)
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

    Использует предзагруженные значки из badges_map вместо N+1 запросов.
    """
    contact = _format_contact(match)

    # Форматируем профиль с batch-загруженными значками
    caption = await _format_profile_with_batch_badges(match, viewer, badges_map)
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


async def _format_profile_with_batch_badges(
    user: dict,
    viewer: dict,
    badges_map: dict[int, list[dict]],
) -> str:
    """Форматирует профиль с использованием предзагруженных значков.

    Оптимизация: вместо вызова format_profile_async (который делает N+1 запрос
    get_user_badges) — используем batch-загруженные значки.
    """
    from data.content import daily_question
    from services.compatibility import fire_level, gender_emoji, interests_text

    name = user["name"] or "Без имени"
    age = user["age"]
    city = user["city"] or "—"
    verified = " ✅" if user["verified"] else ""
    lines = [f"<b>{name}</b>{verified}, {age} {gender_emoji(user['gender'])}  •  📍 {city}"]

    # Значки из batch-загрузки
    badge_line = format_user_badges_inline_batch(badges_map, user["tg_id"])
    if badge_line:
        lines.append(badge_line)

    interests = interests_text(user["interests"])
    if interests != "—":
        lines.append(f"\n🏷 {interests}")

    if user["daily_a"]:
        q = daily_question(user["daily_q"] or 0)
        lines.append(f"\n💭 <i>{q}</i>\n— {user['daily_a']}")

    if user["bio"]:
        lines.append(f"\n📝 {user['bio']}")

    fire = fire_level(user["rating"] or 0)
    lines.append(f"\n{fire}  Симпатий: {user['rating'] or 0}")

    # Совместимость
    pct = compatibility(viewer["interests"], user["interests"])
    common = common_interests(viewer["interests"], user["interests"])
    bar = compat_bar(pct)
    lines.append(f"\n💞 Совместимость: <b>{pct}%</b>\n{bar}")
    if common:
        lines.append("🏷 Общее: " + ", ".join(common))

    return "\n".join(lines)


def _format_contact(user: dict) -> str:
    """Форматирует контакт пользователя."""
    if user.get("username"):
        return Format.CONTACT_USERNAME.format(user["username"])
    return Format.CONTACT_LINK.format(user["tg_id"], user["name"])
