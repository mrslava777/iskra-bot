"""NSFW middleware — проверяет ВСЕ фото перед обработкой.

Проверяет:
1. Фото анкеты (регистрация, редактирование) — через moderate_profile_photo
2. Фото в анонимном чате — через moderate_photo_message
3. Фото в поддержке — через moderate_photo_message
4. Любые другие фото от пользователей — через moderate_photo_message

Если фото заблокировано — отменяет обработку update'а.
"""
import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

from states import Reg, Edit

log = logging.getLogger("iskra.nsfw_middleware")

# States where photo is for PROFILE (not chat)
_PROFILE_PHOTO_STATES = {
    Reg.photo.state,
    Reg.extra_photos.state,
    Edit.photos.state,
}


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

        # Определяем тип фото: профильное или чатовое
        is_profile_photo = current_state in _PROFILE_PHOTO_STATES

        # Проверяем фото
        try:
            if is_profile_photo:
                log.info("NSFWMiddleware: profile photo detected, using moderate_profile_photo")
                from services.nsfw_moderation import moderate_profile_photo
                photo_file_id = event.photo[-1].file_id
                allowed, reason = await moderate_profile_photo(bot, event.from_user.id, photo_file_id)

                if not allowed:
                    log.info("NSFWMiddleware: BLOCKED profile photo from user %d: %s",
                             event.from_user.id, reason)
                    try:
                        msg_text = (
                            "<b>⚠️ Фото не подходит для анкеты</b>\n\n"
                            "Обнаружен запрещённый контент. "
                            "Пожалуйста, загрузите другое фото."
                        )
                        await event.answer(msg_text, parse_mode="HTML")
                        log.info("NSFWMiddleware: profile rejection notification sent")
                    except Exception as e:
                        log.warning("NSFWMiddleware: failed to send notification: %s", e)
                    return None
                else:
                    log.info("NSFWMiddleware: profile photo PASSED checks")
            else:
                log.info("NSFWMiddleware: chat photo detected, using moderate_photo_message")
                from services.nsfw_moderation import moderate_photo_message
                blocked = await moderate_photo_message(bot, event)

                if blocked:
                    log.info("NSFWMiddleware: BLOCKED chat photo from user %d (state=%s)",
                             event.from_user.id, current_state)
                    return None
                else:
                    log.info("NSFWMiddleware: chat photo PASSED checks")

        except Exception as e:
            log.error("NSFWMiddleware: check failed for user %d: %s", event.from_user.id, e, exc_info=True)

        return await handler(event, data)
