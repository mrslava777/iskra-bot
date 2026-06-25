"""Точка входа — polling + health-сервер."""
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

import database as db
from config import BOT_TOKEN
from handlers import setup_routers
from health import start_health_server

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("iskra")


def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан! Установи переменную окружения.")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(setup_routers())

    async def _on_startup() -> None:
        await db.init_db()
        log.info("База инициализирована: %s", db.DB_PATH)
        await start_health_server()

    dp.startup.register(_on_startup)

    try:
        asyncio.run(dp.start_polling(bot))
    except KeyboardInterrupt:
        log.info("Остановка...")


if __name__ == "__main__":
    main()
