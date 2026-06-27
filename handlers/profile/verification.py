"""Верификация профиля — отправка фото, одобрение/отклонение админом."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.user_repo as user_repo
from config import ADMIN_IDS
from data.constants import EMOJI, Format, Message
from data.enums import CallbackPrefix, VerifyAction
from keyboards import profile_kb, verify_kb
from states import Verify

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:verify")
async def on_request_verify(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает фото для верификации."""
    user = await user_repo.get_user(call.from_user.id)
    if user.get("verified"):
        await call.answer(f"{EMOJI.VERIFIED} Ты уже верифицирован!")
        return
    await call.message.edit_text(Format.VERIFICATION_REQUEST)
    await state.set_state(Verify.photo)
    await call.answer()


@router.message(Verify.photo, F.photo)
async def on_verify_photo(message: Message, state: FSMContext) -> None:
    """Отправляет фото админам на проверку."""
    photo_id = message.photo[-1].file_id
    await state.clear()

    user = await user_repo.get_user(message.from_user.id)
    name = user["name"] if user else "?"

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                admin_id,
                photo=photo_id,
                caption=f"🔍 <b>Запрос верификации</b>\n\n"
                        f"Пользователь: <b>{name}</b>\n"
                        f"ID: <code>{message.from_user.id}</code>",
                reply_markup=verify_kb(message.from_user.id),
            )
        except Exception:
            pass

    await message.answer(
        Message.VERIFICATION_SENT,
        reply_markup=profile_kb(has_daily=bool(user.get("daily_a"))),
    )


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.APPROVE.value}:"))
async def on_approve_verify(call: CallbackQuery) -> None:
    """Админ одобряет верификацию."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    await user_repo.upsert_user(tg_id, verified=1)
    await call.answer(f"{EMOJI.VERIFIED} Верифицирован")
    await call.message.edit_text(call.message.caption + f"\n\n{EMOJI.VERIFIED} <b>Верифицирован</b>")
    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_APPROVED)
    except Exception:
        pass


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.REJECT.value}:"))
async def on_reject_verify(call: CallbackQuery) -> None:
    """Админ отклоняет верификацию."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    await call.answer(f"{EMOJI.DISLIKE} Отклонено")
    await call.message.edit_text(call.message.caption + f"\n\n{EMOJI.DISLIKE} <b>Отклонено</b>")
    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_REJECTED)
    except Exception:
        pass
