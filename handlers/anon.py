"""Свидание вслепую 🎭 — анонимный чат с подбором собеседника.\n\nПоток:\n  • кнопка «🎭 Свидание вслепую» → ищем собеседника или встаём в очередь;\n  • как только нашёлся второй желающий — соединяем две стороны;\n  • сообщения (текст, фото, голосовые и т.п.) пересылаются анонимно через бота;\n  • «🎭 Открыться» — если оба нажали, показываем анкеты и создаём мэтч;\n  • «⏹ Завершить» / /stop — выходим из свидания.\n"""
from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from .browse import _announce_match
from keyboards import ANON_CHAT_MENU, MAIN_MENU, anon_queue_kb, anon_session_kb

router = Router()

BTN = "🎭 Свидание вслепую"
STOP_BTN = "⏹ Завершить свидание"

INTRO = (
    "🎭 <b>Свидание вслепую</b>\n\n"
    "Я соединю тебя с другим человеком — <b>анонимно</b>. "
    "Имя, фото и анкета скрыты: вы просто общаетесь вживую.\n\n"
    "Понравится разговор — жмите «🎭 Открыться». Если согласятся оба, "
    "вы увидите анкеты друг друга и попадёте в мэтчи 💞"
)


class InAnonChat(BaseFilter):
    """Срабатывает только если пользователь сейчас в активной анонимной сессии."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await db.anon_active_partner(event.from_user.id) is not None


async def _notify_matched(bot: Bot, uid: int) -> None:
    try:
        await bot.send_message(
            uid,
            "✨ <b>Собеседник найден!</b>\nОбщайтесь анонимно — просто пиши сюда, "
            "я всё передам. Можно отправлять и фото, и голосовые 🙂",
            reply_markup=ANON_CHAT_MENU,
        )
        await bot.send_message(
            uid,
            "Когда захочешь раскрыть анкету — жми «🎭 Открыться».",
            reply_markup=anon_session_kb(),
        )
    except Exception:
        pass


@router.message(F.text == BTN)
async def blind_date(message: Message, state: FSMContext, bot: Bot) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — отправь /start.")
        return
    await state.clear()
    await db.touch_activity(message.from_user.id)

    status, partner = await db.anon_find_or_queue(message.from_user.id)

    if status == "in_session":
        await message.answer(
            "Ты уже на свидании 🎭 Просто пиши — я передам собеседнику.",
            reply_markup=ANON_CHAT_MENU,
        )
    elif status == "waiting":
        await message.answer(
            "Уже ищу тебе собеседника 🔎 Немного терпения…",
            reply_markup=anon_queue_kb(),
        )
    elif status == "queued":
        await message.answer(INTRO)
        await message.answer(
            "🔎 Ищу собеседника… Соединю, как только кто-то ещё зайдёт. "
            "Можешь пока листать ленту — я напишу, когда найду.",
            reply_markup=anon_queue_kb(),
        )
    elif status == "matched":
        await _notify_matched(bot, message.from_user.id)
        await _notify_matched(bot, partner)


async def _end(uid: int, bot: Bot, notifier: Message | None = None) -> None:
    was_in_queue = await db.anon_in_queue(uid)
    partner = await db.anon_end(uid)

    if partner is None:
        text = "Поиск отменён 🙂" if was_in_queue else "Ты сейчас не на свидании 🙂"
        if notifier is not None:
            await notifier.answer(text, reply_markup=MAIN_MENU)
        else:
            try:
                await bot.send_message(uid, text, reply_markup=MAIN_MENU)
            except Exception:
                pass
        return

    for who in (uid, partner):
        try:
            await bot.send_message(
                who,
                "🎭 Свидание завершено. Захочешь ещё — жми «🎭 Свидание вслепую».",
                reply_markup=MAIN_MENU,
            )
        except Exception:
            pass


@router.message(F.text == STOP_BTN)
async def stop_btn(message: Message, bot: Bot) -> None:
    await _end(message.from_user.id, bot, notifier=message)


@router.message(Command("stop"))
async def stop_cmd(message: Message, bot: Bot) -> None:
    await _end(message.from_user.id, bot, notifier=message)


@router.callback_query(F.data == "anon:cancelq")
async def cancel_queue(call: CallbackQuery, bot: Bot) -> None:
    await call.answer("Поиск отменён")
    await db.anon_leave_queue(call.from_user.id)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer("Поиск отменён. Возвращайся в меню.", reply_markup=MAIN_MENU)


@router.callback_query(F.data == "anon:stop")
async def stop_cb(call: CallbackQuery, bot: Bot) -> None:
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _end(call.from_user.id, bot)


@router.callback_query(F.data == "anon:reveal")
async def reveal(call: CallbackQuery, bot: Bot) -> None:
    s = await db.anon_set_reveal(call.from_user.id)
    await call.answer()
    if s is None:
        await call.message.answer("Свидание уже завершено.", reply_markup=MAIN_MENU)
        return

    partner = s["b_id"] if s["a_id"] == call.from_user.id else s["a_id"]
    both_revealed = s["a_reveal"] and s["b_reveal"]

    if both_revealed:
        # Оба согласны — фиксируем взаимный лайк и мэтч, показываем анкеты
        await db.add_like(s["a_id"], s["b_id"], True)
        await db.add_like(s["b_id"], s["a_id"], True)
        await db.anon_end(call.from_user.id)
        await _announce_match(bot, s["a_id"], s["b_id"])
        for who in (s["a_id"], s["b_id"]):
            try:
                await bot.send_message(
                    who,
                    "🎭 ➡️ 💞 Вы оба открылись! Теперь вы в мэтчах. Удачи! 🔥",
                    reply_markup=MAIN_MENU,
                )
            except Exception:
                pass
    else:
        await call.message.answer("Ты открыл(а)ся 👀 Ждём, решится ли собеседник…")
        try:
            await bot.send_message(
                partner,
                "👀 Собеседник хочет открыться! Нажми «🎭 Открыться» в ответ, "
                "если тоже хочешь увидеть анкету.",
                reply_markup=anon_session_kb(),
            )
        except Exception:
            pass


# Пересылка любых сообщений между собеседниками — только для тех, кто в сессии.
# Регистрируется последним в этом роутере, чтобы кнопки выше срабатывали первыми.
@router.message(InAnonChat())
async def relay(message: Message, bot: Bot) -> None:
    partner = await db.anon_active_partner(message.from_user.id)
    if partner is None:
        return

    # NEW: Увеличиваем счётчик сообщений в анонимном чате
    await db.increment_anon_messages(message.from_user.id)

    try:
        await bot.copy_message(
            chat_id=partner,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        await message.answer("Не получилось доставить сообщение собеседнику 😕")
