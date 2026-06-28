"""Просмотр своей анкеты — /myprofile, кнопка «👤 Моя анкета».

PERF: photo_count + format_profile_async + check_and_award запускаются параллельно.
PERF: HIDE_MENU и badge-уведомления — fire-and-forget.
"""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import repositories.user_repo as user_repo
import repositories.photo_repo as photo_repo
from data.constants import MenuText, Message, Format
from data.enums import Command as Cmd
from keyboards import profile_kb, HIDE_MENU
from services.profile_formatter import format_profile_async
from services.badge_service import check_and_award
from services.badge_formatter import format_badge_card

router = Router()


@router.message(Command(Cmd.MYPROFILE.value[1:]))
@router.message(F.text == MenuText.MY_PROFILE)
async def show_my_profile(message: Message) -> None:
    """Показывает анкету текущего пользователя."""
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return

    # Параллельно: форматирование + счётчик фото + проверка значков
    caption, n_photos, new_badges = await asyncio.gather(
        format_profile_async(user, show_compat=False, show_badges=True),
        photo_repo.photo_count(message.from_user.id),
        check_and_award(message.from_user.id),
    )

    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""
    caption += photo_note
    kb = profile_kb()

    try:
        await message.answer_photo(photo=user["photo_id"], caption=caption, reply_markup=kb)
    except Exception:
        await message.answer(caption, reply_markup=kb)

    # Send HIDE_MENU and badge notifications sequentially but non-blocking to user flow
    # FIX: message.answer() in aiogram 3.x returns SendMessage object, not a coroutine
    # We must await it directly, not pass to fire()
    try:
        await message.answer("👆 Твоя анкета", reply_markup=HIDE_MENU)
    except Exception:
        pass

    for badge in new_badges:
        try:
            await message.answer(format_badge_card(badge, is_new=True))
        except Exception:
            pass
