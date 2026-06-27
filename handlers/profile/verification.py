"""Верификация профиля через кружочек со случайным жестом."""
import random
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.user_repo as user_repo
from config import ADMIN_IDS
from data.constants import EMOJI, Format, Message, Verification as Vrf
from data.enums import CallbackPrefix, VerifyAction
from keyboards import profile_kb, verify_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from services.message_utils import edit_or_caption
from states import Verify

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:verify")
async def on_request_verify(call: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает кружочек для верификации со случайным жестом."""
    user = await user_repo.get_user(call.from_user.id)
    if user.get("verified"):
        await call.answer(f"{EMOJI.VERIFIED} Ты уже верифицирован!")
        return

    gesture = random.choice(Vrf.GESTURES)
    await state.update_data(required_gesture=gesture)

    text = Format.VERIFICATION_REQUEST.format(gesture)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=f"{CallbackPrefix.EDIT.value}:back")],
        ]
    )
    await edit_or_caption(call, text, reply_markup=kb)
    await state.set_state(Verify.video_note)
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:back")
async def on_verify_back(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад — возврат в профиль из верификации."""
    await state.clear()
    user = await user_repo.get_user(call.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    has_daily = bool(user.get("daily_a"))
    try:
        await call.message.edit_text(caption, reply_markup=profile_kb(has_daily=has_daily))
    except Exception:
        await call.message.answer(caption, reply_markup=profile_kb(has_daily=has_daily))
    await call.answer()


@router.message(Verify.video_note, F.video_note)
async def on_verify_video_note(message: Message, state: FSMContext) -> None:
    """Принимает кружочек и отправляет админам на проверку — push + меню."""
    video_note_id = message.video_note.file_id
    data = await state.get_data()
    gesture = data.get("required_gesture", "?")
    await state.clear()

    user = await user_repo.get_user(message.from_user.id)
    name = user["name"] if user else "?"

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_video_note(admin_id, video_note=video_note_id)
            await message.bot.send_message(
                admin_id,
                "🔍 <b>Запрос верификации</b>\n\n"
                "Пользователь: <b>" + name + "</b>\n"
                "ID: <code>" + str(message.from_user.id) + "</code>\n"
                "Требуемый жест: <b>" + gesture + "</b>\n\n"
                "Проверь, что жест виден в кадре и лицо совпадает с анкетой.",
                reply_markup=verify_kb(message.from_user.id),
            )
        except Exception:
            pass

    await message.answer(Message.VERIFICATION_SENT, reply_markup=MAIN_MENU)


@router.message(Verify.video_note)
async def on_verify_invalid(message: Message) -> None:
    """Напоминает, что нужен именно кружочек."""
    await message.answer("🎥 Нужно записать <b>кружочек</b> (видеосообщение), а не фото или текст.")


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.APPROVE.value}:"))
async def on_approve_verify(call: CallbackQuery) -> None:
    """Админ одобряет верификацию — шлёт пуш пользователю."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    await user_repo.upsert_user(tg_id, verified=1)
    await call.answer(f"{EMOJI.VERIFIED} Верифицирован", show_alert=True)
    if call.message.photo:
        await call.message.edit_caption(
            caption=call.message.caption + "\n\n" + f"{EMOJI.VERIFIED} <b>Верифицирован</b>"
        )
    else:
        await call.message.edit_text(
            call.message.text + "\n\n" + f"{EMOJI.VERIFIED} <b>Верифицирован</b>"
        )
    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_APPROVED)
    except Exception:
        pass


@router.callback_query(F.data.startswith(f"{CallbackPrefix.VERIFY.value}:{VerifyAction.REJECT.value}:"))
async def on_reject_verify(call: CallbackQuery) -> None:
    """Админ отклоняет верификацию — шлёт пуш пользователю."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(Message.ADMIN_ONLY, show_alert=True)
        return
    tg_id = int(call.data.split(":")[2])
    await call.answer(f"{EMOJI.DISLIKE} Отклонено", show_alert=True)
    if call.message.photo:
        await call.message.edit_caption(
            caption=call.message.caption + "\n\n" + f"{EMOJI.DISLIKE} <b>Отклонено</b>"
        )
    else:
        await call.message.edit_text(
            call.message.text + "\n\n" + f"{EMOJI.DISLIKE} <b>Отклонено</b>"
        )
    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_REJECTED)
    except Exception:
        pass
