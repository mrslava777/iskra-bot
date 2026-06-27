"""Раздел «Артефакты» — коллекция значков и прогресс."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.badge_repo as badge_repo
import repositories.user_repo as user_repo
from badges import BADGES, RARITY_EMOJI, RARITY_ORDER, rarity_label
from data.constants import EMOJI, MenuText, Message as Msg
from data.enums import BadgeAction, CallbackPrefix, Command as Cmd
from keyboards import badges_kb
from services.badge_formatter import format_badge_card
from services.badge_service import check_and_award, get_user_badges

router = Router()

TOTAL_BADGES = len(BADGES)


def _format_collection(badges: list[dict]) -> str:
    """Текст коллекции значков пользователя."""
    if not badges:
        return Msg.NO_BADGES
    ordered = sorted(badges, key=lambda b: RARITY_ORDER.get(b["rarity"], 0), reverse=True)
    lines = [Msg.BADGE_COLLECTION_TITLE.format(len(badges)), ""]
    for b in ordered:
        emoji = RARITY_EMOJI.get(b["rarity"], "⚪")
        lines.append(f"{b['icon']} <b>{b['name']}</b> {emoji}\n<i>{b['description']}</i>")
    lines.append(f"\n📊 Всего: <b>{len(badges)}</b> / {TOTAL_BADGES}")
    return "\n".join(lines)


@router.message(Command(Cmd.BADGES.value[1:]))
@router.message(F.text == MenuText.BADGES)
async def cmd_badges(message: Message) -> None:
    """Показывает коллекцию артефактов."""
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Msg.CREATE_PROFILE_FIRST)
        return

    new_badges = await check_and_award(message.from_user.id)
    for badge in new_badges:
        await message.answer(format_badge_card(badge, is_new=True))

    badges = await get_user_badges(message.from_user.id)
    await message.answer(_format_collection(badges), reply_markup=badges_kb(len(badges)))


@router.callback_query(F.data == f"{CallbackPrefix.BADGE.value}:{BadgeAction.COLLECTION.value}")
async def cb_collection(call: CallbackQuery) -> None:
    """Обновляет коллекцию."""
    await check_and_award(call.from_user.id)
    badges = await get_user_badges(call.from_user.id)
    try:
        await call.message.edit_text(_format_collection(badges), reply_markup=badges_kb(len(badges)))
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.BADGE.value}:{BadgeAction.PROGRESS.value}")
async def cb_progress(call: CallbackQuery) -> None:
    """Показывает ещё не полученные значки."""
    earned = await badge_repo.get_user_badge_ids(call.from_user.id)
    locked = [b for b in BADGES if b["id"] not in earned]
    if not locked:
        await call.answer("Все артефакты собраны! 🎉", show_alert=True)
        return

    locked.sort(key=lambda b: RARITY_ORDER.get(b["rarity"], 0))
    lines = ["📈 <b>Прогресс Артефактов</b>", ""]
    for b in locked[:10]:
        emoji = RARITY_EMOJI.get(b["rarity"], "⚪")
        lines.append(f"{b['icon']} <b>{b['name']}</b> {emoji} ({rarity_label(b['rarity'])})\n<i>{b['description']}</i>")
    if len(locked) > 10:
        lines.append(f"\n…и ещё {len(locked) - 10}")
    try:
        await call.message.edit_text("\n".join(lines), reply_markup=badges_kb(0))
    except Exception:
        pass
    await call.answer()
