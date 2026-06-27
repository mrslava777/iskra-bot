"""Misc handlers — fallback, /help и другие вспомогательные команды."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from data.constants import EMOJI, MenuText, Message
from data.enums import Command as Cmd
from keyboards import MAIN_MENU

router = Router()


@router.message(Command(Cmd.HELP.value[1:]))
async def cmd_help(message: Message) -> None:
    """Показывает справку."""
    await message.answer(
        f"{EMOJI.FIRE_MID} <b>Момент</b> — знакомства с умом.

"
        f"• {MenuText.SEARCH} — лента с расчётом совместимости
"
        f"• {MenuText.BLIND_DATE} — анонимный чат вживую; откроетесь оба — будет мэтч
"
        f"• {MenuText.LIKES_INBOX} — входящие симпатии
"
        f"• {MenuText.MATCHES} — взаимные лайки и контакты
"
        f"• {MenuText.DAILY_QUESTION} — добавь изюминку в анкету
"
        f"• {MenuText.SETTINGS} — фильтры и видимость

"
        f"Команды: {Cmd.START.value} {Cmd.MYPROFILE.value} {Cmd.BADGES.value} {Cmd.HELP.value} {Cmd.STOP.value} (выйти со свидания)",
        reply_markup=MAIN_MENU,
    )


@router.message(F.text == MenuText.MENU)
async def cmd_menu(message: Message) -> None:
    """Показывает главное меню по кнопке «Меню»."""
    await message.answer("Главное меню:", reply_markup=MAIN_MENU)


@router.message(F.text)
async def fallback(message: Message) -> None:
    """Fallback для неизвестных сообщений."""
    await message.answer(Message.FALLBACK, reply_markup=MAIN_MENU)
