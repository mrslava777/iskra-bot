"""Вопрос дня — добавление/удаление ответа в анкету."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import repositories.user_repo as user_repo
from data.constants import Length, DailyQuestion, EMOJI, Message
from data.enums import CallbackPrefix, EditField
from data.content import daily_question
from keyboards import profile_kb
from services.message_utils import edit_or_caption
from states import Edit

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:{EditField.DAILY.value}")
async def on_daily_question(call: CallbackQuery, state: FSMContext) -> None:
    """Показывает вопрос дня и запрашивает ответ."""
    import time
    day_index = int(time.time() // DailyQuestion.SECONDS_PER_DAY)
    q = daily_question(day_index)
    await edit_or_caption(
        call,
        f"{EMOJI.DAILY_QUESTION} <b>Вопрос дня #{day_index % DailyQuestion.COUNT + 1}</b>

"
        f"<i>{q}</i>

"
        f"Напиши свой ответ (до {Length.DAILY_ANSWER} символов):"
    )
    await state.update_data(daily_q=day_index)
    await state.set_state(Edit.daily)
    await call.answer()


@router.message(Edit.daily, F.text)
async def save_daily_answer(message: Message, state: FSMContext) -> None:
    """Сохраняет ответ на вопрос дня."""
    text = message.text.strip()[:Length.DAILY_ANSWER]
    import time
    day_index = int(time.time() // DailyQuestion.SECONDS_PER_DAY)
    await user_repo.upsert_user(message.from_user.id, daily_q=day_index, daily_a=text)
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    await message.answer(
        Message.DAILY_SAVED,
        reply_markup=profile_kb(has_daily=True),
    )


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:{EditField.DELETE_DAILY.value}")
async def on_delete_daily(call: CallbackQuery) -> None:
    """Удаляет ответ на вопрос дня."""
    await user_repo.upsert_user(call.from_user.id, daily_q=0, daily_a="")
    await call.answer(Message.DAILY_DELETED)
    user = await user_repo.get_user(call.from_user.id)
    await edit_or_caption(
        call,
        Message.DAILY_DELETED,
        reply_markup=profile_kb(has_daily=False),
    )
