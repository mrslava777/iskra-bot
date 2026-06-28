"""Главный файл бота Искра."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database.connection import close_db_pool
from handlers import setup_routers
from health import start_health_server, stop_health_server

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Регистрируем все роутеры
    root_router = setup_routers()
    dp.include_router(root_router)

    # Запускаем health-сервер ПЕРЕД polling
    # Railway ждёт, пока порт откроется
    await start_health_server()

    # Даём Railway время увидеть открытый порт
    await asyncio.sleep(2)

    try:
        await dp.start_polling(bot)
    finally:
        await stop_health_server()
        await bot.session.close()
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
