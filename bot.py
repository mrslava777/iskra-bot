"""Точка входа бота Искра 🔥."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import database as db
from config import BOT_TOKEN, DB_PATH, DB_PERSISTENT
from handlers import setup_routers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("iskra")


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать / моё меню"),
            BotCommand(command="myprofile", description="Моя анкета"),
            BotCommand(command="help", description="Помощь"),
        ]
    )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Укажи переменную окружения BOT_TOKEN "
            "(получи токен у @BotFather)."
        )

    await db.init_db()

    if DB_PERSISTENT:
        log.info("✅ База: %s — постоянное хранилище (Volume), анкеты сохраняются.", DB_PATH)
    else:
        log.warning(
            "⚠️ База: %s — ВРЕМЕННОЕ хранилище. На Railway добавь Volume с mount path "
            "/data, тогда анкеты не будут теряться при перезапуске.",
            DB_PATH,
        )

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    await set_commands(bot)
    log.info("Искра запущена 🔥")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено.")
