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
from health import mark_alive, start_health_server
from services.matching import is_night_mode

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


async def night_mode_notifier(bot: Bot) -> None:
    """Отправляет уведомление о начале/окончании ночного режима."""
    notified_night = False
    while True:
        await asyncio.sleep(300)  # проверяем каждые 5 минут
        night = is_night_mode()

        if night and not notified_night:
            # Начался ночной режим
            users = await db.admin_all_active_ids()
            sent = 0
            for uid in users:
                try:
                    await bot.send_message(
                        uid,
                        "🌙 <b>Ночной режим активирован</b>

"
                        "С 00:00 до 06:00 анкеты становятся загадочнее:
"
                        "• Имена скрыты за псевдонимами
"
                        "• Вопросы — более интимные
"
                        "• Атмосфера тайны и интриги

"
                        "Иногда тени говорят громче слов...",
                    )
                    sent += 1
                except Exception:
                    pass
            log.info("Night mode: notified %s users", sent)
            notified_night = True

        elif not night and notified_night:
            # Рассвет — сбрасываем флаг
            users = await db.admin_all_active_ids()
            sent = 0
            for uid in users:
                try:
                    await bot.send_message(
                        uid,
                        "☀️ <b>Рассвет!</b>

"
                        "Ночной режим завершен. Анкеты снова открыты, "
                        "имена видны, а тайны ночи остались в прошлом.

"
                        "Удачных знакомств!",
                    )
                    sent += 1
                except Exception:
                    pass
            log.info("Sunrise: notified %s users", sent)
            notified_night = False


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Укажи переменную окружения BOT_TOKEN "
            "(получи токен у @BotFather)."
        )

    await db.init_db()

    if DB_PERSISTENT:
        log.info("База: %s — постоянное хранилище (Volume), анкеты сохраняются.", DB_PATH)
    else:
        log.warning(
            "База: %s — ВРЕМЕННОЕ хранилище. На Railway добавь Volume с mount path "
            "/data, тогда анкеты не будут теряться при перезапуске.",
            DB_PATH,
        )

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    # Отмечаем «бот жив» на каждом входящем апдейте (бонус к heartbeat'у).
    @dp.update.outer_middleware()
    async def _alive_middleware(handler, event, data):  # noqa: ANN001
        mark_alive()
        return await handler(event, data)

    # Поднимаем /health для внешнего мониторинга (не влияет на логику бота).
    await start_health_server()

    # Запускаем ночной нотификатор
    asyncio.create_task(night_mode_notifier(bot))

    await set_commands(bot)
    log.info("Искра запущена")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлено.")
