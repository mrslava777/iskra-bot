"""NSFW middleware — проверяет ВСЕ фото перед обработкой.

Проверяет:
1. Фото анкеты (регистрация, редактирование)
2. Фото в анонимном чате
3. Фото в поддержке
4. Любые другие фото от пользователей

Если фото заблокировано — отменяет обработку update'а.
"""
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

log = logging.getLogger("iskra.nsfw_middleware")


class NSFWMiddleware(BaseMiddleware):
    """Middleware для проверки всех фото на NSFW-контент."""

    async def __call__(self, handler, event, data):
        # Работаем только с сообщениями, содержащими фото
        if not isinstance(event, Message) or not event.photo:
            return await handler(event, data)

        # Получаем FSM-состояние если есть
        fsm_context = data.get("state")
        current_state = None
        if fsm_context:
            try:
                current_state = await fsm_context.get_state()
            except Exception:
                pass

        # Получаем бота
        bot = data.get("bot")
        if not bot:
            log.warning("NSFW: bot not found in data, skipping check")
            return await handler(event, data)

        # Проверяем фото
        try:
            from services.nsfw_moderation import moderate_photo_message
            blocked = await moderate_photo_message(bot, event)

            if blocked:
                log.info("NSFW: blocked photo from user %d (state=%s)",
                         event.from_user.id, current_state)
                # Отправляем уведомление пользователю
                try:
                    await event.answer(
                        "<b>Фото заблокировано</b>\n\n"
                        "Контент не прошел автоматическую модерацию. "
                        "Если это ошибка — обратись в поддержку.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return None  # Отменяем обработку — хендлер не вызывается

        except Exception as e:
            log.error("NSFW: check failed for user %d: %s", event.from_user.id, e)
            # При ошибке проверки — пропускаем (fail-open для UX)

        return await handler(event, data)
