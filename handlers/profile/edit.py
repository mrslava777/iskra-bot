"""Редактирование полей анкеты — имя, возраст, город, био, интересы."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.user_repo as user_repo
from data.constants import Length, Age, Interest, EMOJI, Message
from data.enums import CallbackPrefix, EditField
from keyboards import interests_kb, profile_kb
from services.profile_formatter import format_profile_async
from services.message_utils import edit_or_caption
from states import Edit

router = Router()

# Только поля, которые обрабатывает этот модуль (name, age, city, bio, interests)
_EDIT_FIELDS = {
    EditField.NAME.value,
    EditField.AGE.value,
    EditField.CITY.value,
    EditField.BIO.value,
    EditField.INTERESTS.value,
}


async def _send_profile_update(message_or_call, user: dict, prefix: str = "✅ Обновлено!") -> None:
    """Отправляет обновленный профиль с фото и клавиатурой.

    Оптимизация: вместо edit_text/edit_caption (которые теряют фото или не работают
    на текстовых сообщениях) — отправляем новое сообщение с фото.
    """
    import repositories.photo_repo as photo_repo
    from data.constants import Format

    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    n_photos = await photo_repo.photo_count(user["tg_id"])
    photo_note = Format.PHOTO_COUNT.format(n_photos) if n_photos > 1 else ""
    caption += photo_note

    has_daily = bool(user.get("daily_a"))
    kb = profile_kb(has_daily=has_daily)
    text = prefix + "\n\n" + caption

    if isinstance(message_or_call, CallbackQuery):
        # Для callback — редактируем если возможно, иначе новое сообщение
        msg = message_or_call.message
        if msg.photo:
            try:
                await msg.edit_caption(caption=text, reply_markup=kb)
                return
            except Exception:
                pass
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
        # Fallback — новое сообщение
        try:
            await message_or_call.message.answer_photo(photo=user["photo_id"], caption=text, reply_markup=kb)
        except Exception:
            await message_or_call.message.answer(text, reply_markup=kb)
    else:
        # Для message — всегда отправляем фото с подписью
        msg = message_or_call
        try:
            await msg.answer_photo(photo=user["photo_id"], caption=text, reply_markup=kb)
        except Exception:
            await msg.answer(text, reply_markup=kb)


@router.callback_query(F.data.in_({f"{CallbackPrefix.EDIT.value}:{f}" for f in _EDIT_FIELDS}))
async def on_edit_field(call: CallbackQuery, state: FSMContext) -> None:
    """Обработчик выбора поля для редактирования."""
    field = call.data.split(":")[1]
    await state.update_data(edit_field=field)

    prompts = {
        EditField.NAME.value: f"{EMOJI.MESSAGE_LIKE} Введи новое имя (до {Length.NAME} символов):",
        EditField.AGE.value: "🎂 Сколько тебе лет?",
        EditField.CITY.value: f"{EMOJI.LOCATION} Из какого ты города?",
        EditField.BIO.value: "📝 Напиши пару слов о себе (или «-» чтобы удалить):",
    }

    if field == EditField.INTERESTS.value:
        user = await user_repo.get_user(call.from_user.id)
        sel = [int(x) for x in (user["interests"] or "").split(",") if x.strip().isdigit()]
        await edit_or_caption(
            call,
            f"{EMOJI.INTERESTS} Выбери интересы:",
            reply_markup=interests_kb(sel, CallbackPrefix.EDIT_INTEREST.value),
        )
        await state.set_state(Edit.interests)
        await call.answer()
        return

    if field in prompts:
        await edit_or_caption(call, prompts[field])
        await state.set_state(Edit.value)
    await call.answer()


@router.message(Edit.value, F.text)
async def edit_value(message: Message, state: FSMContext) -> None:
    """Сохраняет новое значение поля и показывает обновленный профиль с фото."""
    data = await state.get_data()
    field = data.get("edit_field")
    text = message.text.strip()

    if field == EditField.NAME.value:
        if len(text) > Length.NAME:
            await message.answer(Message.NAME_TOO_LONG)
            return
        await user_repo.upsert_user(message.from_user.id, name=text)

    elif field == EditField.AGE.value:
        if not text.isdigit() or not (Age.MIN <= int(text) <= Age.MAX):
            await message.answer(Message.AGE_INVALID)
            return
        await user_repo.upsert_user(message.from_user.id, age=int(text))

    elif field == EditField.CITY.value:
        await user_repo.upsert_user(message.from_user.id, city=text[:Length.CITY])

    elif field == EditField.BIO.value:
        bio = "" if text == "-" else text[:Length.BIO]
        await user_repo.upsert_user(message.from_user.id, bio=bio)

    else:
        await message.answer("Неизвестное поле.")
        return

    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    await _send_profile_update(message, user)


@router.callback_query(Edit.interests, F.data.startswith(f"{CallbackPrefix.EDIT_INTEREST.value}:"))
async def edit_interests(call: CallbackQuery, state: FSMContext) -> None:
    """Обработчик выбора интересов."""
    payload = call.data.split(":")[1]
    user = await user_repo.get_user(call.from_user.id)
    sel = [int(x) for x in (user["interests"] or "").split(",") if x.strip().isdigit()]

    if payload == "done":
        interests = ",".join(str(i) for i in sel)
        await user_repo.upsert_user(call.from_user.id, interests=interests)
        await state.clear()
        user = await user_repo.get_user(call.from_user.id)
        await _send_profile_update(call, user, "✅ Интересы обновлены!")
        return

    idx = int(payload)
    if idx in sel:
        sel.remove(idx)
    elif len(sel) < Interest.MAX_SELECTED:
        sel.append(idx)
    else:
        await call.answer(Message.MAX_INTERESTS)
        return

    await user_repo.upsert_user(call.from_user.id, interests=",".join(str(i) for i in sel))
    await call.message.edit_reply_markup(reply_markup=interests_kb(sel, CallbackPrefix.EDIT_INTEREST.value))
    await call.answer()
