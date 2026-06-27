"""Вопрос дня — добавление/удаление ответа в анкету."""
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import repositories.user_repo as user_repo
from data.constants import Length, DailyQuestion, EMOJI, MenuText, Message
from data.enums import CallbackPrefix, EditField
from data.content import daily_question
from keyboards import MAIN_MENU, profile_kb
from services.message_utils import edit_or_caption
from services.profile_formatter import format_profile_async
from states import Edit

router = Router()


@router.message(F.text == MenuText.DAILY_QUESTION)
async def cmd_daily_question(message: Message, state: FSMContext) -> None:
    """Обработчик кнопки «Вопрос дня» из главного меню."""
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer(Message.CREATE_PROFILE_FIRST)
        return

    day_index = int(time.time() // DailyQuestion.SECONDS_PER_DAY)
    current_q = daily_question(day_index)

    # Если уже отвечал сегодня — показываем текущий ответ с возможностью удалить
    if user.get("daily_a") and user.get("daily_q") == day_index:
        text = (
            f"{EMOJI.DAILY_QUESTION} <b>Вопрос дня #{day_index % DailyQuestion.COUNT + 1}</b>

"
            f"<i>{current_q}</i>

"
            f"💭 <b>Твой ответ:</b>
"
            f"{user['daily_a']}

"
            f"Хочешь изменить ответ? Пришли новый текст (до {Length.DAILY_ANSWER} символов) или нажми «Удалить» в профиле."
        )
        await message.answer(text, reply_markup=MAIN_MENU)
        return

    # Новый вопрос — запрашиваем ответ
    q = daily_question(day_index)
    text = (
        f"{EMOJI.DAILY_QUESTION} <b>Вопрос дня #{day_index % DailyQuestion.COUNT + 1}</b>

"
        f"<i>{q}</i>

"
        f"Напиши свой ответ (до {Length.DAILY_ANSWER} символов):"
    )
    await message.answer(text, reply_markup=MAIN_MENU)
    await state.update_data(daily_q=day_index)
    await state.set_state(Edit.daily)


@router.message(Edit.daily, F.text)
async def save_daily_answer(message: Message, state: FSMContext) -> None:
    """Сохраняет ответ на вопрос дня."""
    text = message.text.strip()[:Length.DAILY_ANSWER]
    day_index = int(time.time() // DailyQuestion.SECONDS_PER_DAY)
    await user_repo.upsert_user(message.from_user.id, daily_q=day_index, daily_a=text)
    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    caption = await format_profile_async(user, show_compat=False, show_badges=True)
    await message.answer(
        Message.DAILY_SAVED + "

" + caption,
        reply_markup=profile_kb(has_daily=True),
    )


@router.callback_query(F.data == f"{CallbackPrefix.EDIT.value}:{EditField.DELETE_DAILY.value}")
async def on_delete_daily(call: CallbackQuery) -> None:
    """Удаляет ответ на вопрос дня из профиля."""
    await user_repo.upsert_user(call.from_user.id, daily_q=0, daily_a="")
    await call.answer(Message.DAILY_DELETED)
    user = await user_repo.get_user(call.from_user.id)
    await edit_or_caption(
        call,
        Message.DAILY_DELETED,
        reply_markup=profile_kb(has_daily=False),
    )
