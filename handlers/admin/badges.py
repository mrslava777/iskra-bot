"""Статистика артефактов в админ-панели."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

import repositories.badge_stats_repo as badge_stats_repo
import repositories.user_repo as user_repo
from badges import BADGES, RARITY_EMOJI, rarity_label
from data.constants import EMOJI, Admin, Message
from data.enums import AdminAction, CallbackPrefix
from keyboards import back_kb
from services.admin_service import is_admin

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BADGES.value}")
async def cb_badges_stats(call: CallbackQuery) -> None:
    """Показывает статистику по значкам.

    Оптимизация: batch-запрос get_all_badge_counts() вместо N отдельных запросов.
    """
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)

    counts = await badge_stats_repo.get_all_badge_counts()

    lines = [f"{EMOJI.BADGE_TROPHY} <b>Статистика Артефактов</b>"]
    for badge in BADGES:
        count = counts.get(badge["id"], 0)
        rarity_emoji = RARITY_EMOJI.get(badge["rarity"], "⚪")
        lines.append(
            f"{badge['icon']} <b>{badge['name']}</b> — {count} чел. "
            f"({rarity_emoji} {rarity_label(badge['rarity'])})")

    top = await badge_stats_repo.get_top_collectors(limit=Admin.TOP_COLLECTORS_LIMIT)
    if top:
        lines.append("")
        lines.append(f"<b>Топ-{Admin.TOP_COLLECTORS_LIMIT} коллекционеров:</b>")
        tg_ids = [r["tg_id"] for r in top]
        names = await user_repo.get_user_names_batch(tg_ids)
        for i, r in enumerate(top, 1):
            name = names.get(r["tg_id"], f"ID:{r['tg_id']}")
            lines.append(f"{i}. <b>{name}</b> — {r['cnt']} значков")

    await call.message.edit_text("\n".join(lines), reply_markup=back_kb())
