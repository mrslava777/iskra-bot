"""Редактирование полей анкеты — имя, возраст, город, био, интересы.

FIX v8: Allowlist для полей редактирования + валидация через validation.py.
        Используется safe_send из services.safe_send.
"""
import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.user_repo as user_repo
from data.constants import Age, Interest, EMOJI, Message as Msg
from data.enums import CallbackPrefix, EditField
from keyboards import interests_kb, profile_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from services.safe_send import safe_send
from services.validation import sanitize_name, sanitize_city, sanitize_bio, validate_age
from states import Edit

router = Router()
log = logging.getLogger("iskra.profile.edit")

# Только поля, которые обрабатывает этот модуль
_EDIT_FIELDS = {
    EditField.NAME.value,
    EditField.AGE.value,
    EditField.CITY.value,
    EditField.BIO.value,
    EditField.INTERESTS.value,
}


@router.callback_query(F.data.in_({f"{CallbackPrefix.EDIT.value}:{f}" for f in _EDIT_FIELDS}))
async def on_edit_field(call: CallbackQuery, state: FSMContext) -> None:
    """Обработчик выбора поля для редактирования."""
    field = call.data.split(":")[1]

    if field not in _EDIT_FIELDS:
        log.warning("Rejected unknown edit field: %r from user %d", field, call.from_user.id)
        await call.answer("Неизвестное поле", show_alert=True)
        return

    await state.update_data(edit_field=field)

    prompts = {
        EditField.NAME.value: f"{EMOJI.MESSAGE_LIKE} Введи новое имя (до 32 символов):",
        EditField.AGE.value: "🎂 Сколько тебе лет?",
        EditField.CITY.value: f"{EMOJI.LOCATION} Из какого ты города?",
        EditField.BIO.value: "📝 Напиши пару слов о себе (или «-» чтобы удалить):",
    }

    if field == EditField.INTERESTS.value:
        user = await user_repo.get_user(call.from_user.id)
        sel = [int(x) for x in (user["interests"] or "").split(",") if x.strip().isdigit()]
        await call.message.answer(
            f"{EMOJI.INTERESTS} Выбери интересы:",
            reply_markup=interests_kb(sel, CallbackPrefix.EDIT_INTEREST.value),
        )
        await state.set_state(Edit.interests)
        await call.answer()
        return

    if field in prompts:
        await call.message.answer(prompts[field])
        await state.set_state(Edit.value)
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:back")
async def on_edit_back(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад — возврат в профиль."""
    await state.clear()
    try:
        user = await user_repo.get_user(call.from_user.id)
        caption = await format_profile_async(user, show_compat=False, show_badges=True)
        try:
            await call.message.edit_text(caption, reply_markup=profile_kb())
        except Exception as e:
            log.debug("edit_text failed, using answer: %s", e)
            await call.message.answer(caption, reply_markup=profile_kb())
    except Exception as e:
        log.error("Failed to go back from edit for %d: %s", call.from_user.id, e)
    await call.answer()


@router.message(Edit.value, F.text)
async def edit_value(message: Message, state: FSMContext) -> None:
    """Сохраняет новое значение поля с валидацией."""
    data = await state.get_data()
    field = data.get("edit_field")
    text = message.text.strip()

    if field not in _EDIT_FIELDS:
        log.warning("Rejected unknown edit field in handler: %r from user %d", field, message.from_user.id)
        await message.answer("Неизвестное поле.", reply_markup=MAIN_MENU)
        return

    try:
        if field == EditField.NAME.value:
            name = await sanitize_name(text)
            if name is None:
                await message.answer(Msg.NAME_TOO_LONG)
                return
            await user_repo.upsert_user(message.from_user.id, name=name)

        elif field == EditField.AGE.value:
            age = validate_age(text)
            if age is None:
                await message.answer(Msg.AGE_INVALID)
                return
            await user_repo.upsert_user(message.from_user.id, age=age)

        elif field == EditField.CITY.value:
            city = await sanitize_city(text)
            if city is None:
                await message.answer("Неверное название города.")
                return
            await user_repo.upsert_user(message.from_user.id, city=city)

        elif field == EditField.BIO.value:
            bio = await sanitize_bio(text)
            if bio is None:
                await message.answer(
                    "⚠️ <b>Био содержит недопустимый контент</b>\n\n"
                    "Пожалуйста, уберите запрещённые слова или HTML-теги и попробуйте снова.",
                    parse_mode="HTML",
                )
                return
            await user_repo.upsert_user(message.from_user.id, bio=bio)

        else:
            await message.answer("Неизвестное поле.", reply_markup=MAIN_MENU)
            return
    except Exception as e:
        log.error("Failed to update field %r for %d: %s", field, message.from_user.id, e)
        await message.answer("Не удалось сохранить 😕 Попробуй ещё раз.", reply_markup=MAIN_MENU)
        return

    await state.clear()
    await message.answer("✅ Обновлено!", reply_markup=MAIN_MENU)


@router.callback_query(Edit.interests, F.data.startswith(f"{CallbackPrefix.EDIT_INTEREST.value}:"))
async def edit_interests(call: CallbackQuery, state: FSMContext) -> None:
    """Обработчик выбора интересов."""
    payload = call.data.split(":")[1]
    try:
        user = await user_repo.get_user(call.from_user.id)
        sel = [int(x) for x in (user["interests"] or "").split(",") if x.strip().isdigit()]

        if payload == "done":
            interests = ",".join(str(i) for i in sel)
            await user_repo.upsert_user(call.from_user.id, interests=interests)
            await state.clear()
            await call.answer("✅ Интересы обновлены!", show_alert=True)
            await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
            return

        idx = int(payload)
        if idx in sel:
            sel.remove(idx)
        elif len(sel) < Interest.MAX_SELECTED:
            sel.append(idx)
        else:
            await call.answer(Msg.MAX_INTERESTS)
            return

        await user_repo.upsert_user(call.from_user.id, interests=",".join(str(i) for i in sel))
        await call.message.edit_reply_markup(reply_markup=interests_kb(sel, CallbackPrefix.EDIT_INTEREST.value))
        await call.answer()
    except Exception as e:
        log.error("Failed to update interests for %d: %s", call.from_user.id, e)
        await call.answer("Ошибка обновления интересов", show_alert=True)
