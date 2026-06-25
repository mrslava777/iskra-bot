"""Регистрация анкеты (FSM) и /start."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import database as db
from ..keyboards import MAIN_MENU, extra_photos_kb, gender_kb, interests_kb, seeking_kb
from ..services.matching import profile_caption
from ..services.badges import check_and_award, format_badge_card
from ..states import Reg

router = Router()

WELCOME = (
    "🔥 <b>Искра</b> — бот знакомств, где важнее не только фото.\n\n"
    "Здесь мы считаем <b>совместимость по интересам</b>, подсказываем, "
    "с чего начать разговор, и каждый день задаём новый вопрос для анкеты.\n\n"
    "Давай создадим твою анкету за минуту. Как тебя зовут?"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if user and user["name"] and user["photo_id"]:
        await db.touch_activity(message.from_user.id)
        await message.answer(
            "С возвращением! 🔥 Выбирай, что делаем дальше.", reply_markup=MAIN_MENU
        )
        return
    await message.answer(WELCOME)
    await state.set_state(Reg.name)


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) > 32:
        await message.answer("Слишком длинно 🙂 До 32 символов, пожалуйста.")
        return
    await state.update_data(name=name)
    await message.answer("Сколько тебе лет?")
    await state.set_state(Reg.age)


@router.message(Reg.age, F.text)
async def reg_age(message: Message, state: FSMContext) -> None:
    txt = message.text.strip()
    if not txt.isdigit() or not (14 <= int(txt) <= 99):
        await message.answer("Введи возраст числом (14–99).")
        return
    await state.update_data(age=int(txt))
    await message.answer("Твой пол?", reply_markup=gender_kb("rgender"))
    await state.set_state(Reg.gender)


@router.callback_query(Reg.gender, F.data.startswith("rgender:"))
async def reg_gender(call: CallbackQuery, state: FSMContext) -> None:
    g = call.data.split(":")[1]
    await state.update_data(gender=g)
    await call.message.edit_text("Кого хочешь видеть в ленте?")
    await call.message.answer("Выбери:", reply_markup=seeking_kb("rseek"))
    await state.set_state(Reg.seeking)
    await call.answer()


@router.callback_query(Reg.seeking, F.data.startswith("rseek:"))
async def reg_seeking(call: CallbackQuery, state: FSMContext) -> None:
    s = call.data.split(":")[1]
    await state.update_data(seeking=s)
    await call.message.edit_text("Из какого ты города?")
    await state.set_state(Reg.city)
    await call.answer()


@router.message(Reg.city, F.text)
async def reg_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip()[:48])
    await state.update_data(sel_interests=[])
    await message.answer(
        "Выбери интересы (до 5) — по ним считается совместимость 💞",
        reply_markup=interests_kb([], "rint"),
    )
    await state.set_state(Reg.interests)


@router.callback_query(Reg.interests, F.data.startswith("rint:"))
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
    elif len(sel) < 5:
        sel.append(idx)
    else:
        await call.answer("Можно максимум 5 🙂", show_alert=False)
        return
    await state.update_data(sel_interests=sel)
    await call.message.edit_reply_markup(reply_markup=interests_kb(sel, "rint"))
    await call.answer()


@router.message(Reg.bio, F.text)
async def reg_bio(message: Message, state: FSMContext) -> None:
    bio = "" if message.text.strip() == "-" else message.text.strip()[:300]
    await state.update_data(bio=bio)
    await message.answer("📷 Последний шаг — пришли своё фото.")
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext) -> None:
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    interests = ",".join(str(i) for i in data.get("sel_interests", []))
    await db.upsert_user(
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
    # Сохраняем главное фото в галерею
    await db.sync_photos_to_gallery(message.from_user.id)
    await db.touch_activity(message.from_user.id)

    await state.update_data(extra_count=0)
    await state.set_state(Reg.extra_photos)
    await message.answer(
        "📸 Хочешь добавить ещё фото? (до 4 дополнительных)\n"
        "Просто отправь фото или нажми «Пропустить».",
        reply_markup=extra_photos_kb(),
    )


@router.callback_query(Reg.extra_photos, F.data == "regph:skip")
async def reg_skip_extra(call: CallbackQuery, state: FSMContext) -> None:
    await _finish_registration(call.message, call.from_user.id, state)
    await call.answer()


@router.message(Reg.extra_photos, F.photo)
async def reg_extra_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = data.get("extra_count", 0)
    if count >= 4:
        await message.answer("Максимум 5 фото 🙂 Сохраняю анкету!")
        await _finish_registration(message, message.from_user.id, state)
        return
    photo_id = message.photo[-1].file_id
    await db.add_photo(message.from_user.id, photo_id)
    count += 1
    await state.update_data(extra_count=count)
    remaining = 4 - count
    if remaining > 0:
        await message.answer(
            f"✅ Фото добавлено! ({count + 1}/5)\nМожно ещё {remaining} шт. или нажми «Пропустить».",
            reply_markup=extra_photos_kb(),
        )
    else:
        await message.answer("✅ Все 5 фото загружены!")
        await _finish_registration(message, message.from_user.id, state)


async def _finish_registration(message: Message, user_id: int, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(user_id)
    n_photos = await db.photo_count(user_id)
    photo_note = f"\n📸 Фото в анкете: {n_photos}" if n_photos > 1 else ""

    # Проверяем значки при завершении регистрации
    new_badges = await check_and_award(user_id)

    await message.answer_photo(
        photo=user["photo_id"],
        caption=f"✨ Готово! Вот твоя анкета:\n\n{profile_caption(user)}{photo_note}",
    )

    # Показываем новые значки
    for badge in new_badges:
        await message.answer(format_badge_card(badge, is_new=True))

    await message.answer(
        "Поехали искать! Жми «🔍 Смотреть анкеты».", reply_markup=MAIN_MENU
    )


@router.message(Reg.extra_photos)
async def reg_extra_invalid(message: Message) -> None:
    await message.answer("Отправь фото 📷 или нажми «Пропустить».", reply_markup=extra_photos_kb())


@router.message(Reg.photo)
async def reg_photo_invalid(message: Message) -> None:
    await message.answer("Нужно именно фото 📷 (как изображение, не файлом).")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🔥 <b>Искра</b> — знакомства с умом.\n\n"
        "• 🔍 Смотреть анкеты — лента с расчётом совместимости\n"
        "• 🎭 Свидание вслепую — анонимный чат вживую; откроетесь оба — будет мэтч\n"
        "• 💌 Кто меня лайкнул — входящие симпатии\n"
        "• 💞 Мэтчи — взаимные лайки и контакты\n"
        "• 🎯 Вопрос дня — добавь изюминку в анкету\n"
        "• 🏆 Артефакты — коллекционные значки за активность\n"
        "• ⚙️ Настройки — фильтры и видимость\n\n"
        "Команды: /start /myprofile /badges /help /stop (выйти со свидания)",
        reply_markup=MAIN_MENU,
    )
