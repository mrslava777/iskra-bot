"""Точка входа — polling + health-сервер."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

import database as db
from config import BOT_TOKEN
from handlers import setup_routers
from health import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# aiohttp access-логи health-сервера не засоряют вывод.
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
log = logging.getLogger("iskra")


def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан! Установи переменную окружения.")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    root = setup_routers()

    # Централизованный обработчик ошибок: ни одно исключение в хендлере больше
    # не теряется молча — пишем полный traceback в лог.
    @root.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка в апдейте: %s", event.exception)
        return True

    dp.include_router(root)

    async def _on_startup() -> None:
        await db.init_db()
        log.info("База инициализирована: %s", db.DB_PATH)
        await start_health_server()

    async def _on_shutdown() -> None:
        log.info("Остановка: закрываю БД и сессию бота…")
        await db.close_db()
        await bot.session.close()

    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    try:
        asyncio.run(dp.start_polling(bot))
    except KeyboardInterrupt:
        log.info("Остановка по Ctrl+C…")


if __name__ == "__main__":
    main()
