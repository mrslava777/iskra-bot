"""Просмотр и редактирование своей анкеты, вопрос дня, настройки."""
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from data.content import daily_question
from keyboards import (
    MAIN_MENU,
    interests_kb,
    profile_kb,
    seeking_kb,
    settings_kb,
)
from services.matching import parse_interests, profile_caption
from states import Edit

router = Router()


async def _send_profile(message: Message, user) -> None:
    caption = "👤 <b>Твоя анкета</b>\n\n" + profile_caption(user)
    try:
        await message.answer_photo(
            photo=user["photo_id"], caption=caption, reply_markup=profile_kb()
        )
    except Exception:
        await message.answer(caption, reply_markup=profile_kb())


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


@router.callback_query(F.data.startswith("setseek:"))
async def set_seeking(call: CallbackQuery) -> None:
    s = call.data.split(":")[1]
    await db.upsert_user(call.from_user.id, seeking=s)
    label = {"m": "парней", "f": "девушек", "any": "всех"}[s]
    await call.message.edit_text(f"✅ Теперь показываю {label}.")
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
