"""Админ-панель: вход /admin, главное меню и статистика."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.settings_repo as settings_repo
from data.constants import EMOJI, Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import admin_menu_kb, back_kb
from services.admin_service import is_admin
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

ADMIN_TITLE = f"{EMOJI.ADMIN} <b>Админ-панель Момент</b>\n\nВыбери раздел:"


@router.message(Command(Cmd.ADMIN.value[1:]))
async def cmd_admin(message: Message) -> None:
    """Открывает админ-панель."""
    if not is_admin(message.from_user.id):
        return
    await message.answer(ADMIN_TITLE, reply_markup=admin_menu_kb())


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.MENU.value}")
async def cb_menu(call: CallbackQuery) -> None:
    """Возврат в главное меню админки."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    try:
        await call.message.edit_text(ADMIN_TITLE, reply_markup=admin_menu_kb())
    except Exception:
        await call.message.answer(ADMIN_TITLE, reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.STATS.value}")
async def cb_stats(call: CallbackQuery) -> None:
    """Показывает статистику бота."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    s = await settings_repo.stats()
    ext = await settings_repo.admin_extended_stats()

    text = (
        f"{Format.STATS_HEADER}\n"
        f"{Format.STATS_USERS.format(s['users'] or 0)}"
        f"{Format.STATS_ACTIVE.format(s['active'] or 0)}"
        f"{Format.STATS_NEW_TODAY.format(ext['new_today'] or 0)}"
        f"{Format.STATS_BANNED.format(ext['banned'] or 0)}"
        f"{Format.STATS_LIKES.format(s['likes'] or 0)}"
        f"{Format.STATS_MATCHES.format(s['matches'] or 0)}"
        f"{Format.STATS_REPORTS.format(ext['reports'] or 0)}"
        f"{Format.STATS_MALES.format(ext['males'] or 0)}"
        f"{Format.STATS_FEMALES.format(ext['females'] or 0)}"
    )
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()
