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
        log.info("NSFWMiddleware: processing event type=%s", type(event).__name__)

        # Работаем только с сообщениями, содержащими фото
        if not isinstance(event, Message):
            log.debug("NSFWMiddleware: not a Message, skipping")
            return await handler(event, data)

        if not event.photo:
            log.debug("NSFWMiddleware: no photo in message, skipping")
            return await handler(event, data)

        log.info("NSFWMiddleware: photo detected from user %d", event.from_user.id)

        # Получаем FSM-состояние если есть
        fsm_context = data.get("state")
        current_state = None
        if fsm_context:
            try:
                current_state = await fsm_context.get_state()
                log.info("NSFWMiddleware: current state=%s", current_state)
            except Exception as e:
                log.warning("NSFWMiddleware: failed to get state: %s", e)

        # Получаем бота
        bot = data.get("bot")
        if not bot:
            log.warning("NSFWMiddleware: bot not found in data, skipping check")
            return await handler(event, data)

        # Проверяем фото
        try:
            log.info("NSFWMiddleware: calling moderate_photo_message...")
            from services.nsfw_moderation import moderate_photo_message
            blocked = await moderate_photo_message(bot, event)
            log.info("NSFWMiddleware: moderate_photo_message returned blocked=%s", blocked)

            if blocked:
                log.info("NSFWMiddleware: BLOCKED photo from user %d (state=%s)",
                         event.from_user.id, current_state)
                # Отправляем уведомление пользователю
                try:
                    msg_text = (
                        "<b>⚠️ Фото заблокировано</b>\n\n"
                        "Контент не прошел автоматическую модерацию. "
                        "Если это ошибка — обратись в поддержку."
                    )
                    await event.answer(msg_text, parse_mode="HTML")
                    log.info("NSFWMiddleware: notification sent to user")
                except Exception as e:
                    log.warning("NSFWMiddleware: failed to send notification: %s", e)
                return None  # Отменяем обработку — хендлер не вызывается
            else:
                log.info("NSFWMiddleware: photo PASSED checks")

        except Exception as e:
            log.error("NSFWMiddleware: check failed for user %d: %s", event.from_user.id, e, exc_info=True)
            # При ошибке проверки — пропускаем (fail-open для UX)

        return await handler(event, data)
