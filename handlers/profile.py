"""Просмотр и редактирование своей анкеты, вопрос дня, настройки."""
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
from data.content import daily_question
from keyboards import (
    MAIN_MENU,
    confirm_delete_kb,
    interests_kb,
    photos_manage_kb,
    profile_kb,
    seeking_kb,
    settings_kb,
)
from services.matching import parse_interests, profile_caption
from states import Edit, Verify

import random

GESTURES = [
    ("✌️ два пальца (V)", "peace"),
    ("👍 большой палец вверх", "thumbup"),
    ("🤟 рокерская коза", "rock"),
    ("☝️ один палец вверх", "pointup"),
    ("✋ открытая ладонь", "palm"),
]

router = Router()


async def _send_profile(message: Message, user) -> None:
    caption = "👤 <b>Твоя анкета</b>\n\n" + profile_caption(user)
    has_daily = bool(user["daily_a"])
    try:
        await message.answer_photo(
            photo=user["photo_id"], caption=caption, reply_markup=profile_kb(has_daily)
        )
    except Exception:
        await message.answer(caption, reply_markup=profile_kb(has_daily))


@router.message(F.text == "👤 Моя анкета")
@router.message(Command("myprofile"))
async def my_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("У тебя ещё нет анкеты. Отправь /start.")
        return
    await _send_profile(message, user)


# ---------- Редактирование ----------

FIELD_PROMPTS = {
    "name": "Введи новое имя:",
    "age": "Введи возраст (14–99):",
    "city": "Введи город:",
    "bio": "Напиши новый текст о себе (до 300 символов):",
}


@router.callback_query(F.data.startswith("ed:"))
async def on_edit(call: CallbackQuery, state: FSMContext) -> None:
    field = call.data.split(":")[1]

    if field in FIELD_PROMPTS:
        await state.update_data(edit_field=field)
        await state.set_state(Edit.value)
        await call.message.answer(FIELD_PROMPTS[field])
        await call.answer()
        return

    if field == "photo":
        await state.set_state(Edit.value)
        await state.update_data(edit_field="photo")
        await call.message.answer("Пришли новое фото 📷")
        await call.answer()
        return

    if field == "photos":
        await db.sync_photos_to_gallery(call.from_user.id)
        photos = await db.get_photos(call.from_user.id)
        count = len(photos)
        if count > 0:
            from aiogram.types import InputMediaPhoto
            if count == 1:
                await call.message.answer_photo(
                    photo=photos[0]["photo_id"],
                    caption=f"📸 Твои фото ({count}/5):",
                    reply_markup=photos_manage_kb(count),
                )
            else:
                media = [InputMediaPhoto(media=p["photo_id"]) for p in photos]
                media[0] = InputMediaPhoto(media=photos[0]["photo_id"], caption=f"📸 Твои фото ({count}/5):")
                await call.message.answer_media_group(media)
                await call.message.answer("Управление фото:", reply_markup=photos_manage_kb(count))
        else:
            await call.message.answer(
                "У тебя ещё нет фото.",
                reply_markup=photos_manage_kb(0),
            )
        await state.set_state(Edit.photos)
        await call.answer()
        return

    # NEW: редактирование голосового
    if field == "voice":
        await state.set_state(Edit.voice)
        await call.message.answer(
            "🎙 <b>Голосовое приветствие</b>\n\n"
            "Запиши новое голосовое (до 1 минуты) или нажми «Удалить», чтобы убрать.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🗑 Удалить голосовое", callback_data="ed:del_voice")],
                    [InlineKeyboardButton(text="↩️ Отмена", callback_data="ed:cancel_voice")],
                ]
            ),
        )
        await call.answer()
        return

    if field == "del_voice":
        await db.upsert_user(call.from_user.id, voice_id=None, voice_duration=0)
        await call.answer("🗑 Голосовое удалено")
        user = await db.get_user(call.from_user.id)
        await _send_profile(call.message, user)
        return

    if field == "cancel_voice":
        await state.clear()
        await call.answer("Отменено")
        user = await db.get_user(call.from_user.id)
        await _send_profile(call.message, user)
        return

    if field == "verify":
        user = await db.get_user(call.from_user.id)
        if user and user.keys() and "verified" in user.keys() and user["verified"]:
            await call.answer("✅ Ты уже верифицирован!", show_alert=True)
            return
        status = await db.get_verification_status(call.from_user.id)
        if status == "pending":
            await call.answer("⏳ Твоя заявка на рассмотрении", show_alert=True)
            return
        gesture_text, gesture_key = random.choice(GESTURES)
        await state.update_data(verify_gesture=gesture_key, verify_gesture_text=gesture_text)
        await state.set_state(Verify.photo)
        text = (
            "🎭 <b>Верификация профиля</b>\n\n"
            "Запиши кружочек (видеосообщение) с жестом:\n"
            f"<b>{gesture_text}</b>\n\n"
            "Нажми на кнопку микрофона 🎙, переключись на видео 📹 "
            "и отправь кружочек\n\n"
            "Это подтвердит, что ты — реальный человек. "
            "После проверки администратором в анкете появится ✅"
        )
        await call.message.answer(text)
        await call.answer()
        return

    if field == "interests":
        user = await db.get_user(call.from_user.id)
        sel = parse_interests(user["interests"])
        await state.update_data(sel_interests=sel)
        await state.set_state(Edit.interests)
        await call.message.answer(
            "Обнови интересы (до 5):", reply_markup=interests_kb(sel, "eint")
        )
        await call.answer()
        return

    if field == "daily":
        await _ask_daily(call.message, state)
        await call.answer()
        return

    if field == "del_daily":
        await db.upsert_user(call.from_user.id, daily_q=None, daily_a=None)
        await call.answer("🗑 Ответ на вопрос дня удалён", show_alert=True)
        user = await db.get_user(call.from_user.id)
        if user:
            caption = "👤 <b>Твоя анкета</b>\n\n" + profile_caption(user)
            try:
                await call.message.edit_caption(caption=caption, reply_markup=profile_kb(False))
            except Exception:
                try:
                    await call.message.edit_text(text=caption, reply_markup=profile_kb(False))
                except Exception:
                    pass
        return


@router.message(Edit.value, F.photo)
async def edit_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("edit_field") != "photo":
        return
    await db.upsert_user(message.from_user.id, photo_id=message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Фото обновлено!")
    user = await db.get_user(message.from_user.id)
    await _send_profile(message, user)


@router.message(Edit.value, F.text)
async def edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("edit_field")
    txt = message.text.strip()

    if field == "age":
        if not txt.isdigit() or not (14 <= int(txt) <= 99):
            await message.answer("Возраст числом, 14–99.")
            return
        await db.upsert_user(message.from_user.id, age=int(txt))
    elif field == "name":
        await db.upsert_user(message.from_user.id, name=txt[:32])
    elif field == "city":
        await db.upsert_user(message.from_user.id, city=txt[:48])
    elif field == "bio":
        await db.upsert_user(message.from_user.id, bio=txt[:300])
    else:
        await message.answer("Пришли фото 📷")
        return

    await state.clear()
    await message.answer("✅ Обновлено!")
    user = await db.get_user(message.from_user.id)
    await _send_profile(message, user)


# NEW: обработка голосового при редактировании
@router.message(Edit.voice, F.voice)
async def edit_voice(message: Message, state: FSMContext) -> None:
    voice = message.voice
    if voice.duration > 60:
        await message.answer("Слишком длинно! Максимум 1 минута. Попробуй ещё раз.")
        return
    await db.upsert_user(
        message.from_user.id,
        voice_id=voice.file_id,
        voice_duration=voice.duration,
    )
    await state.clear()
    await message.answer("✅ Голосовое приветствие обновлено!")
    user = await db.get_user(message.from_user.id)
    await _send_profile(message, user)


@router.message(Edit.voice)
async def edit_voice_invalid(message: Message) -> None:
    await message.answer(
        "Нужно именно голосовое сообщение 🎙 (до 1 минуты).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить голосовое", callback_data="ed:del_voice")],
                [InlineKeyboardButton(text="↩️ Отмена", callback_data="ed:cancel_voice")],
            ]
        ),
    )


@router.callback_query(Edit.interests, F.data.startswith("eint:"))
async def edit_interests(call: CallbackQuery, state: FSMContext) -> None:
    payload = call.data.split(":")[1]
    data = await state.get_data()
    sel = data.get("sel_interests", [])

    if payload == "done":
        interests = ",".join(str(i) for i in sel)
        await db.upsert_user(call.from_user.id, interests=interests)
        await state.clear()
        await call.message.edit_text("✅ Интересы обновлены!")
        user = await db.get_user(call.from_user.id)
        await _send_profile(call.message, user)
        await call.answer()
        return

    idx = int(payload)
    if idx in sel:
        sel.remove(idx)
    elif len(sel) < 5:
        sel.append(idx)
    else:
        await call.answer("Максимум 5 🙂")
        return
    await state.update_data(sel_interests=sel)
    await call.message.edit_reply_markup(reply_markup=interests_kb(sel, "eint"))
    await call.answer()


# ---------- Вопрос дня ----------

def _day_index() -> int:
    return int(time.time() // 86400)


async def _ask_daily(message: Message, state: FSMContext) -> None:
    di = _day_index() % 1000
    q = daily_question(di)
    await state.update_data(daily_idx=di)
    await state.set_state(Edit.daily)
    await message.answer(f"🎯 <b>Вопрос дня:</b>\n{q}\n\nНапиши свой ответ (он появится в анкете):")


@router.message(F.text == "🎯 Вопрос дня")
async def daily_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — /start.")
        return
    await _ask_daily(message, state)


@router.message(Edit.daily, F.text)
async def daily_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    di = data.get("daily_idx", _day_index() % 1000)
    await db.upsert_user(
        message.from_user.id, daily_q=di, daily_a=message.text.strip()[:200]
    )
    await state.clear()
    await message.answer(
        "✨ Ответ добавлен в анкету! Это делает тебя заметнее 🔥", reply_markup=MAIN_MENU
    )


# ---------- Настройки ----------

@router.message(F.text == "⚙️ Настройки")
async def settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — /start.")
        return
    await message.answer(
        "⚙️ <b>Настройки</b>\nУправляй видимостью и фильтрами:",
        reply_markup=settings_kb(bool(user["active"])),
    )


@router.callback_query(F.data.startswith("set:"))
async def on_setting(call: CallbackQuery, state: FSMContext) -> None:
    action = call.data.split(":")[1]
    user = await db.get_user(call.from_user.id)

    if action == "toggle":
        new_active = 0 if user["active"] else 1
        await db.upsert_user(call.from_user.id, active=new_active)
        await call.message.edit_reply_markup(reply_markup=settings_kb(bool(new_active)))
        await call.answer("Анкета скрыта" if not new_active else "Анкета активна")
        return

    if action == "age":
        await state.set_state(Edit.filters_age)
        await call.message.answer(
            "Укажи диапазон возраста через дефис, напр. <code>20-30</code>:"
        )
        await call.answer()
        return

    if action == "seeking":
        await call.message.answer("Кого показывать в ленте?", reply_markup=seeking_kb("setseek"))
        await call.answer()
        return

    if action == "support":
        from keyboards import support_kb
        await call.message.answer(
            "📩 <b>Поддержка</b>\n\nС чем у вас возникла проблема?",
            reply_markup=support_kb(),
        )
        await call.answer()
        return

    if action == "delete":
        await call.message.answer(
            "⚠️ <b>Ты уверен(а)?</b>\n\n"
            "Будут удалены: анкета, лайки, мэтчи, жалобы и все связанные данные.\n"
            "Это действие <b>необратимо</b>.",
            reply_markup=confirm_delete_kb(),
        )
        await call.answer()
        return

    if action == "delete_confirm":
        await db.delete_user(call.from_user.id)
        await state.clear()
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer(
            "✅ Аккаунт полностью удалён. Все данные стёрты.\n\n"
            "Если захочешь вернуться — просто отправь /start 🔥"
        )
        await call.answer()
        return

    if action == "delete_cancel":
        try:
            await call.message.edit_text("↩️ Удаление отменено. Твой аккаунт на месте 🙂")
        except Exception:
            pass
        await call.answer()
        return


@router.callback_query(F.data.startswith("setseek:"))
async def set_seeking(call: CallbackQuery) -> None:
    s = call.data.split(":")[1]
    await db.upsert_user(call.from_user.id, seeking=s)
    label = {"m": "парней", "f": "девушек", "any": "всех"}[s]
    await call.message.edit_text(f"✅ Теперь показываю {label}.")
    await call.answer()


# ---------- Управление фотогалереей ----------

@router.callback_query(F.data == "ph:add")
async def photo_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Edit.photos)
    await state.update_data(photos_action="add")
    await call.message.answer("📷 Отправь фото для добавления:")
    await call.answer()


@router.callback_query(F.data.startswith("ph:del:"))
async def photo_delete(call: CallbackQuery, state: FSMContext) -> None:
    pos = int(call.data.split(":")[2])
    photos = await db.get_photos(call.from_user.id)
    if pos >= len(photos):
        await call.answer("Фото не найдено")
        return
    if len(photos) <= 1:
        await call.answer("Нельзя удалить единственное фото!", show_alert=True)
        return
    await db.remove_photo(call.from_user.id, pos)
    new_photos = await db.get_photos(call.from_user.id)
    if new_photos:
        await db.set_main_photo(call.from_user.id, new_photos[0]["photo_id"])
    count = len(new_photos)
    await call.message.edit_text(
        f"🗑 Фото удалено! Осталось: {count}/5",
        reply_markup=photos_manage_kb(count),
    )
    await call.answer()


@router.callback_query(F.data == "ph:back")
async def photo_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(call.from_user.id)
    await _send_profile(call.message, user)
    await call.answer()


@router.message(Edit.photos, F.photo)
async def photo_add_receive(message: Message, state: FSMContext) -> None:
    count = await db.photo_count(message.from_user.id)
    if count >= 5:
        await message.answer("Максимум 5 фото! Сначала удали одно из существующих.")
        return
    photo_id = message.photo[-1].file_id
    pos = await db.add_photo(message.from_user.id, photo_id)
    new_count = count + 1
    await state.clear()
    await message.answer(
        f"✅ Фото добавлено! ({new_count}/5)",
        reply_markup=photos_manage_kb(new_count),
    )


# ---------- Верификация ----------

@router.message(Verify.photo, F.video_note)
async def verify_video_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gesture = data.get("verify_gesture", "unknown")
    gesture_text = data.get("verify_gesture_text", "")
    video_id = message.video_note.file_id
    await db.submit_verification(message.from_user.id, video_id, gesture)
    await state.clear()
    await message.answer(
        "✅ Заявка на верификацию отправлена!\n"
        "Администратор проверит твоё видео. Обычно это занимает несколько часов.\n"
        "Ты получишь уведомление о результате.",
        reply_markup=MAIN_MENU,
    )
    from config import ADMIN_IDS
    from keyboards import verify_kb
    user = await db.get_user(message.from_user.id)
    name = user["name"] if user else "?"
    username = f"@{user['username']}" if user and user["username"] else "—"
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_video_note(
                admin_id,
                video_note=video_id,
            )
            await message.bot.send_message(
                admin_id,
                text=(
                    f"🎭 <b>Заявка на верификацию</b>\n\n"
                    f"👤 {name} ({username})\n"
                    f"🆔 {message.from_user.id}\n"
                    f"Жест: {gesture_text}\n\n"
                    "Проверь и одобри/отклони:"
                ),
                reply_markup=verify_kb(message.from_user.id),
            )
        except Exception:
            pass


@router.message(Verify.photo)
async def verify_video_invalid(message: Message) -> None:
    await message.answer(
        "Нужен именно кружочек (видеосообщение) 🎥\n"
        "Нажми на кнопку микрофона 🎙, переключись на видео 📹 и отправь кружочек."
    )


@router.callback_query(F.data.startswith("vrf:"))
async def on_verify_decision(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    action = parts[1]
    tg_id = int(parts[2])
    if action == "approve":
        await db.approve_verification(tg_id)
        await call.message.edit_text(
            text=call.message.text + "\n\n✅ <b>ОДОБРЕНО</b>",
            reply_markup=None,
        )
        try:
            await call.bot.send_message(
                tg_id, "✅ Поздравляем! Твой профиль верифицирован! Теперь в анкете видна ✅"
            )
        except Exception:
            pass
    elif action == "reject":
        await db.reject_verification(tg_id)
        await call.message.edit_text(
            text=call.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            reply_markup=None,
        )
        try:
            await call.bot.send_message(
                tg_id,
                "❌ К сожалению, верификация не пройдена.\n"
                "Убедись, что на кружочке хорошо видно твоё лицо и жест, и попробуй снова."
            )
        except Exception:
            pass
    await call.answer()


@router.message(Edit.filters_age, F.text)
async def set_age_filter(message: Message, state: FSMContext) -> None:
    txt = message.text.strip().replace(" ", "")
    if "-" not in txt:
        await message.answer("Формат: <code>мин-макс</code>, напр. 20-30.")
        return
    lo, _, hi = txt.partition("-")
    if not (lo.isdigit() and hi.isdigit()):
        await message.answer("Нужны числа, напр. 20-30.")
        return
    lo_i, hi_i = int(lo), int(hi)
    if lo_i > hi_i or lo_i < 14 or hi_i > 99:
        await message.answer("Диапазон 14–99, мин не больше макс.")
        return
    await db.upsert_user(message.from_user.id, min_age=lo_i, max_age=hi_i)
    await state.clear()
    await message.answer(f"✅ Фильтр возраста: {lo_i}–{hi_i}.", reply_markup=MAIN_MENU)
