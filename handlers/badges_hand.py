"""Хендлеры системы Артефактов (значков)."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import MAIN_MENU, badges_kb, badge_detail_kb
from services.badges import (
    check_and_award,
    format_badge_card,
    format_badges_list,
    get_badge_progress,
    get_user_badges,
)

router = Router()


@router.message(Command("badges"))
@router.message(F.text == "🏆 Артефакты")
async def cmd_badges(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — /start.")
        return

    # Проверяем новые значки
    new_badges = await check_and_award(message.from_user.id)

    badges = await get_user_badges(message.from_user.id)
    text = format_badges_list(badges)

    if new_badges:
        # Показываем новые значки отдельными сообщениями
        for badge in new_badges:
            card = format_badge_card(badge, is_new=True)
            await message.answer(card)

    # Показываем общую коллекцию
    total = len(badges)
    text += f"\n\n📊 Всего: <b>{total}</b> / 15"
    await message.answer(text, reply_markup=badges_kb(total))


@router.callback_query(F.data == "bdg:collection")
async def show_collection(call: CallbackQuery) -> None:
    badges = await get_user_badges(call.from_user.id)
    text = format_badges_list(badges)
    total = len(badges)
    text += f"\n\n📊 Всего: <b>{total}</b> / 15"
    await call.message.edit_text(text, reply_markup=badges_kb(total))
    await call.answer()


@router.callback_query(F.data == "bdg:progress")
async def show_progress(call: CallbackQuery) -> None:
    progress = await get_badge_progress(call.from_user.id)
    if not progress:
        await call.answer("Все значки получены! 🎉", show_alert=True)
        return

    lines = ["📈 <b>Прогресс Артефактов</b>\n"]
    # Сортируем по редкости
    from data.badges import RARITY_ORDER
    items = sorted(progress.items(), key=lambda x: RARITY_ORDER[x[1]["badge"]["rarity"]])

    for badge_id, info in items[:8]:  # Показываем первые 8
        b = info["badge"]
        prog = info["progress"]
        lines.append(f"{b['icon']} <b>{b['name']}</b> — {prog}")

    if len(items) > 8:
        lines.append(f"\n...и ещё {len(items) - 8}")

    await call.message.edit_text("\n".join(lines), reply_markup=badges_kb(0))
    await call.answer()


@router.callback_query(F.data == "bdg:back")
async def badges_back(call: CallbackQuery) -> None:
    await call.message.delete()
    await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
    await call.answer()
