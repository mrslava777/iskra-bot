"""Админ-панель: вход /admin, главное меню и статистика.

FIX v8: логирование ошибок загрузки статистики.
        Используется safe_send из services.safe_send.
"""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.settings_repo as settings_repo
from data.constants import EMOJI, Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import admin_menu_kb, back_kb
from services.admin_service import is_admin
from services.safe_send import safe_send


log = logging.getLogger("iskra.admin.stats")

router = Router()

ADMIN_TITLE = f"{EMOJI.ADMIN} <b>Админ-панель Момент</b>\n\nВыбери раздел:"


@router.message(Command(Cmd.ADMIN.value[1:]))
async def cmd_admin(message: Message) -> None:
    """Открывает админ-панель."""
    if not is_admin(message.from_user.id):
        return
    await safe_send(
        message.answer(ADMIN_TITLE, reply_markup=admin_menu_kb()),
        log_prefix="admin_open",
    )


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.MENU.value}")
async def cb_menu(call: CallbackQuery) -> None:
    """Возврат в главное меню админки."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    await safe_send(
        call.message.edit_text(ADMIN_TITLE, reply_markup=admin_menu_kb()),
        fallback=call.message.answer(ADMIN_TITLE, reply_markup=admin_menu_kb()),
        log_prefix="admin_menu",
    )
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.STATS.value}")
async def cb_stats(call: CallbackQuery) -> None:
    """Показывает статистику бота."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)

    try:
        s = await settings_repo.stats()
    except Exception as e:
        log.error("Failed to load stats for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки статистики", show_alert=True)
        return

    try:
        ext = await settings_repo.admin_extended_stats()
    except Exception as e:
        log.error("Failed to load extended stats for admin %d: %s", call.from_user.id, e)
        ext = {}

    text = (
        f"{Format.STATS_HEADER}"
        f"{Format.STATS_USERS.format(s.get('users') or 0)}"
        f"{Format.STATS_ACTIVE.format(s.get('active') or 0)}"
        f"{Format.STATS_NEW_TODAY.format(ext.get('new_today') or 0)}"
        f"{Format.STATS_BANNED.format(ext.get('banned') or 0)}"
        f"{Format.STATS_LIKES.format(s.get('likes') or 0)}"
        f"{Format.STATS_MATCHES.format(s.get('matches') or 0)}"
        f"{Format.STATS_REPORTS.format(ext.get('reports') or 0)}"
        f"{Format.STATS_MALES.format(ext.get('males') or 0)}"
        f"{Format.STATS_FEMALES.format(ext.get('females') or 0)}"
    )
    await safe_send(
        call.message.edit_text(text, reply_markup=back_kb()),
        log_prefix="admin_stats",
    )
    await call.answer()
