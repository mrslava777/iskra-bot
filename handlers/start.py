"""Регистрация анкеты (FSM) и /start.

PERF: _finish_registration параллелизирует загрузку user + photo_count + badges.
"""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo
from data.constants import Length, Photo, Interest, EMOJI, Message, Format
from data.enums import CallbackPrefix, Command as Cmd
from keyboards import MAIN_MENU, extra_photos_kb, gender_kb, interests_kb, seeking_kb
from services.profile_formatter import format_profile
from services.badge_service import check_and_award
from services.badge_formatter import format_badge_card
from states import Reg

router = Router()


async def _safe_touch(tg_id: int) -> None:
    """Fire-and-forget touch_activity с перехватом ошибок."""
    try:
        await user_repo.touch_activity(tg_id)
    except Exception:
        pass


WELCOME = (
    f"{EMOJI.FIRE_MID} <b>Момент</b> — бот знакомств, где важно не только фото.\n\n"
    "Здесь мы считаем <b>совместимость по интересам</b>, подсказываем, "
    "с чего начать разговор, и даём уникальные артефакты за активность.\n\n"
    "Давай создадим твою анкету за минуту. Как тебя зовут?"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if user and user["name"] and user["photo_id"]:
        # touch_activity — fire-and-forget, не блокирует ответ
        # FIX: create_task for actual coroutine
        asyncio.create_task(_safe_touch(message.from_user.id))
        await message.answer(Message.WELCOME_BACK, reply_markup=MAIN_MENU)
        return
    await message.answer(WELCOME)
    await state.set_state(Reg.name)


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) > Length.NAME:
        await message.answer(Message.NAME_TOO_LONG)
        return
    await state.update_data(name=name)
    await message.answer("Сколько тебе лет?")
    await state.set_state(Reg.age)


@router.message(Reg.age, F.text)
async def reg_age(message: Message, state: FSMContext) -> None:
    txt = message.text.strip()
    if not txt.isdigit() or not (14 <= int(txt) <= 99):
        await message.answer(Message.AGE_INVALID)
        return
    await state.update_data(age=int(txt))
    await message.answer("Твой пол?", reply_markup=gender_kb(CallbackPrefix.REG_GENDER.value))
    await state.set_state(Reg.gender)


@router.callback_query(Reg.gender, F.data.startswith(f"{CallbackPrefix.REG_GENDER.value}:"))
async def reg_gender(call: CallbackQuery, state: FSMContext) -> None:
    g = call.data.split(":")[1]
    await state.update_data(gender=g)
    await call.message.edit_text("Кого хочешь видеть в ленте?")
    await call.message.answer("Выбери:", reply_markup=seeking_kb(CallbackPrefix.REG_SEEKING.value))
    await state.set_state(Reg.seeking)
    await call.answer()


@router.callback_query(Reg.seeking, F.data.startswith(f"{CallbackPrefix.REG_SEEKING.value}:"))
async def reg_seeking(call: CallbackQuery, state: FSMContext) -> None:
    s = call.data.split(":")[1]
    await state.update_data(seeking=s)
    await call.message.edit_text("Из какого ты города?")
    await state.set_state(Reg.city)
    await call.answer()


@router.message(Reg.city, F.text)
async def reg_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip()[:Length.CITY])
    await state.update_data(sel_interests=[])
    await message.answer(
        f"Выбери интересы (до {Interest.MAX_SELECTED}) — по ним считается совместимость {EMOJI.COMPAT}",
        reply_markup=interests_kb([], CallbackPrefix.REG_INTEREST.value),
    )
    await state.set_state(Reg.interests)


@router.callback_query(Reg.interests, F.data.startswith(f"{CallbackPrefix.REG_INTEREST.value}:"))
async def reg_interests(call: CallbackQuery, state: FSMContext) -> None:
    payload = call.data.split(":")[1]
    data = await state.get_data()
    sel = data.get("sel_interests", [])

    if payload == "done":
        await call.message.edit_text(
            "📝 Напиши пару слов о себе (или отправь «-», чтобы пропустить)."
        )
        await state.set_state(Reg.bio)
        await call.answer()
        return

    idx = int(payload)
    if idx in sel:
        sel.remove(idx)
    elif len(sel) < Interest.MAX_SELECTED:
        sel.append(idx)
    else:
        await call.answer(Message.MAX_INTERESTS, show_alert=True)
        return
    await state.update_data(sel_interests=sel)
    await call.message.edit_reply_markup(reply_markup=interests_kb(sel, CallbackPrefix.REG_INTEREST.value))
    await call.answer()


@router.message(Reg.bio, F.text)
async def reg_bio(message: Message, state: FSMContext) -> None:
    bio = "" if message.text.strip() == "-" else message.text.strip()[:Length.BIO]
    await state.update_data(bio=bio)
    await message.answer("📷 Последний шаг — пришли своё фото.")
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext) -> None:
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    interests = ",".join(str(i) for i in data.get("sel_interests", []))
    await user_repo.upsert_user(
        message.from_user.id,
        username=message.from_user.username,
        name=data["name"],
        age=data["age"],
        gender=data["gender"],
        seeking=data["seeking"],
        city=data["city"],
        bio=data.get("bio", ""),
        interests=interests,
        photo_id=photo_id,
        active=1,
    )
    await photo_repo.sync_photos_to_gallery(message.from_user.id)
    await user_repo.touch_activity(message.from_user.id)

    await state.update_data(extra_count=0)
    await state.set_state(Reg.extra_photos)
    await message.answer(
        f"📸 Хочешь добавить ещё фото? (до {Photo.MAX_EXTRA} дополнительных)\n"
        "Просто отправь фото или нажми «Пропустить».",
        reply_markup=extra_photos_kb(),
    )


@router.callback_query(Reg.extra_photos, F.data == f"{CallbackPrefix.REG_PHOTO.value}:skip")
async def reg_skip_extra(call: CallbackQuery, state: FSMContext) -> None:
    await _finish_registration(call.message, call.from_user.id, state)
    await call.answer("✅ Анкета готова!", show_alert=True)


@router.message(Reg.extra_photos, F.photo)
async def reg_extra_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = data.get("extra_count", 0)
    if count >= Photo.MAX_EXTRA:
        await message.answer(Message.MAX_PHOTOS + " Сохраняю анкету!")
        await _finish_registration(message, message.from_user.id, state)
        return
    photo_id = message.photo[-1].file_id
    await photo_repo.add_photo(message.from_user.id, photo_id)
    count += 1
    await state.update_data(extra_count=count)
    remaining = Photo.MAX_EXTRA - count
    if remaining > 0:
        await message.answer(
            Format.PHOTO_ADDED.format(count + 1, Photo.MAX_TOTAL) + f"\n{Format.PHOTOS_REMAINING.format(remaining)}",
            reply_markup=extra_photos_kb(),
        )
    else:
        await message.answer("✅ Все 5 фото загружены!")
        await _finish_registration(message, message.from_user.id, state)


async def _finish_registration(message: Message, user_id: int, state: FSMContext) -> None:
    await state.clear()

    # Параллельно: user + photo_count + badges
    user, n_photos, new_badges = await asyncio.gather(
        user_repo.get_user(user_id),
        photo_repo.photo_count(user_id),
        check_and_award(user_id),
    )
    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""

    await message.answer_photo(
        photo=user["photo_id"],
        caption=f"{Message.PROFILE_COMPLETE}{format_profile(user)}{photo_note}",
    )

    for badge in new_badges:
        await message.answer(format_badge_card(badge, is_new=True))

    await message.answer(Message.LETS_GO, reply_markup=MAIN_MENU)


@router.message(Reg.extra_photos)
async def reg_extra_invalid(message: Message) -> None:
    await message.answer(Message.SEND_PHOTO_OR_SKIP, reply_markup=extra_photos_kb())


@router.message(Reg.photo)
async def reg_photo_invalid(message: Message) -> None:
    await message.answer(Message.SEND_PHOTO)
