"""Хендлер для просмотра уровня отношений с мэтчем."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import MAIN_MENU
from services.relationships import get_relationship, format_status

router = Router()


@router.callback_query(F.data.startswith("rel:"))
async def on_rel_status(call: CallbackQuery) -> None:
    """Показывает уровень отношений с конкретным мэтчем."""
    parts = call.data.split(":")
    if len(parts) < 2:
        await call.answer("Ошибка")
        return
    partner_id = int(parts[1])

    rel = await get_relationship(call.from_user.id, partner_id)
    if not rel:
        await call.answer("Нет данных об отношениях")
        return

    text = format_status(rel, call.from_user.id)
    await call.message.answer(f"💞 <b>Уровень отношений</b>

{text}")
    await call.answer()
