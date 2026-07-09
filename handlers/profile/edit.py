"""Редактирование полей анкеты — имя, возраст, город, био, интересы."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.user_repo as user_repo
from data.constants import Length, Age, Interest, EMOJI, Message
from data.enums import CallbackPrefix, EditField
from keyboards import interests_kb, profile_kb, MAIN_MENU
from services.profile_formatter import format_profile_async
from states import Edit
import asyncio


log = logging.getLogger("iskra." + __name__.split(".")[-1])

async def _safe_send(coro, fallback=None):
    """Safe wrapper for Telegram send operations."""
    try:
        return await coro
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception:
            pass
    except TelegramForbiddenError:
        pass
    except Exception:
        if fallback:
            try:
                return await fallback
            except Exception:
                pass
    return None

router = Router()

# Только поля, которые обрабатывает этот модуль (name, age, city, bio, interests)
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
        # Отправляем новое сообщение с inline-клавиатурой
        await call.message.answer(
            f"{EMOJI.INTERESTS} Выбери интересы:",
            reply_markup=interests_kb(sel, CallbackPrefix.EDIT_INTEREST.value),
        )
        await state.set_state(Edit.interests)
        await call.answer()
        return

    if field in prompts:
        # Отправляем новое сообщение — чтобы появилась клавиатура с буквами
        await call.message.answer(prompts[field])
        await state.set_state(Edit.value)
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:back")
async def on_edit_back(call: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад — возврат в профиль из любого редактирования."""
    await state.clear()
    user = await user_repo.get_user(call.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    try:
        await call.message.edit_text(caption, reply_markup=profile_kb())
    except Exception:
        await call.message.answer(caption, reply_markup=profile_kb())
    await call.answer()


@router.message(Edit.value, F.text)
async def edit_value(message: Message, state: FSMContext) -> None:
    """Сохраняет новое значение поля и показывает push + главное меню."""
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
        await message.answer("Неизвестное поле.", reply_markup=MAIN_MENU)
        return

    await state.clear()
    # Push-уведомление + главное меню
    await message.answer("✅ Обновлено!", reply_markup=MAIN_MENU)


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
        # Push-уведомление + главное меню
        await call.answer("✅ Интересы обновлены!", show_alert=True)
        await call.message.answer("Главное меню:", reply_markup=MAIN_MENU)
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
