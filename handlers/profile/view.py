"""Просмотр своей анкеты — /myprofile, кнопка «👤 Моя анкета».

PERF: photo_count + format_profile_async + check_and_award запускаются параллельно.
FIX v8: логирование ошибок вместо bare pass.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import repositories.user_repo as user_repo
import repositories.photo_repo as photo_repo
from data.constants import MenuText, Message, Format
from data.enums import Command as Cmd
from keyboards import profile_kb
from services.profile_formatter import format_profile_async
from services.badge_service import check_and_award
from services.badge_formatter import format_badge_card

router = Router()
log = logging.getLogger("iskra.profile.view")


@router.message(Command(Cmd.MYPROFILE.value[1:]))
@router.message(F.text == MenuText.MY_PROFILE)
async def show_my_profile(message: Message) -> None:
    """Показывает анкету текущего пользователя."""
    try:
        user = await user_repo.get_user(message.from_user.id)
    except Exception as e:
        log.error("Failed to load user %d for profile view: %s", message.from_user.id, e)
        await message.answer("Не удалось загрузить профиль 😕")
        return

    if not user or not user.get("name"):
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return

    # Параллельно: форматирование + счётчик фото + проверка значков
    try:
        caption, n_photos, new_badges = await asyncio.gather(
            format_profile_async(user, show_compat=False, show_badges=True),
            photo_repo.photo_count(message.from_user.id),
            check_and_award(message.from_user.id),
        )
    except Exception as e:
        log.error("Failed to load profile data for %d: %s", message.from_user.id, e)
        await message.answer("Не удалось загрузить профиль 😕")
        return

    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""
    caption += photo_note
    kb = profile_kb()

    try:
        await message.answer_photo(photo=user["photo_id"], caption=caption, reply_markup=kb)
    except Exception as e:
        log.warning("Failed to send profile photo for %d: %s", message.from_user.id, e)
        try:
            await message.answer(caption, reply_markup=kb)
        except Exception as e2:
            log.error("Failed to send profile text for %d: %s", message.from_user.id, e2)

    # Отправляем уведомления о новых значках (без лишнего "👆 Твоя анкета")
    for badge in new_badges:
        try:
            await message.answer(format_badge_card(badge, is_new=True))
        except Exception as e:
            log.warning("Failed to send badge notification to %d: %s", message.from_user.id, e)
