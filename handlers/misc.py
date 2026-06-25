"""Прочие хендлеры: статистика для админов и фолбэк."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import database as db
from config import ADMIN_IDS
from keyboards import MAIN_MENU

router = Router()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    s = await db.stats()
    await message.answer(
        "📊 <b>Статистика Искры</b>
"
        f"👥 Пользователей: {s['users']}
"
        f"🟢 Активных: {s['active']}
"
        f"❤️ Лайков: {s['likes']}
"
        f"💞 Мэтчей: {s['matches']}"
    )


# Фолбэк — последний роутер, ловит всё прочее
@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer(
        "Не понял 🙂 Пользуйся кнопками меню ниже или отправь /help.",
        reply_markup=MAIN_MENU,
    )
