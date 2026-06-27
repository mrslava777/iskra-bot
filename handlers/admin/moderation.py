"""Модерация — бан, разбан, жалобы."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.settings_repo as settings_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, Admin, Message, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BAN.value}")
async def cb_ban_help(call: CallbackQuery) -> None:
    """Инструкция по бану."""
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    text = (
        f"{EMOJI.REPORT} <b>Бан / Разбан</b>\n\n"
        "Отправь команду:\n"
        f"<code>{Cmd.BAN.value} 123456789</code> — забанить\n"
        f"<code>{Cmd.UNBAN.value} 123456789</code> — разбанить\n\n"
        "Или нажми кнопку бана в разделе «Жалобы»."
    )
    await call.message.edit_text(text, reply_markup=back_kb())


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.REPORTS.value}")
async def cb_reports(call: CallbackQuery) -> None:
    """Показывает последние жалобы.

    Оптимизация: batch-запрос для всех target пользователей вместо N запросов.
    """
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    reports = await settings_repo.admin_recent_reports(limit=Admin.RECENT_REPORTS_LIMIT)
    if not reports:
        return await call.message.edit_text(f"{EMOJI.REPORT} Жалоб нет 🎉", reply_markup=back_kb())

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    target_ids = list(set(r["to_id"] for r in reports))
    users_map = await user_repo.get_user_names_batch(target_ids)

    lines = [f"{EMOJI.REPORT} <b>Последние жалобы:</b>"]
    buttons = []
    for r in reports:
        target_id = r["to_id"]
        name = users_map.get(target_id, "удалён")
        banned = ""
        lines.append(f"• <b>{name}</b> (ID: <code>{target_id}</code>) — {r['report_count']} жалоб(ы){banned}")
        buttons.append([
            InlineKeyboardButton(
                text=f"{EMOJI.REPORT} Бан {target_id}",
                callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.DO_BAN.value, target_id),
            )
        ])
    buttons.append([InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.MENU.value))])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.DO_BAN.value}:"))
async def cb_do_ban(call: CallbackQuery) -> None:
    """Банит пользователя из списка жалоб."""
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])
    await settings_repo.admin_ban_user(tg_id)
    user = await user_repo.get_user(tg_id)
    name = user["name"] if user else "?"
    await call.answer(f"{EMOJI.VERIFIED} {name} забанен")
    await cb_reports(call)


@router.message(Command(Cmd.BAN.value[1:]))
async def cmd_ban(message: Message) -> None:
    """Команда бана."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer(Format.BAN_USAGE)
    tg_id = int(parts[1])
    user = await user_repo.get_user(tg_id)
    if not user:
        return await message.answer(Message.USER_NOT_FOUND)
    await settings_repo.admin_ban_user(tg_id)
    await message.answer(Format.BAN_SUCCESS.format(user["name"], tg_id))


@router.message(Command(Cmd.UNBAN.value[1:]))
async def cmd_unban(message: Message) -> None:
    """Команда разбана."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer(Format.UNBAN_USAGE)
    tg_id = int(parts[1])
    user = await user_repo.get_user(tg_id)
    if not user:
        return await message.answer(Message.USER_NOT_FOUND)
    await settings_repo.admin_unban_user(tg_id)
    await message.answer(Format.UNBAN_SUCCESS.format(user["name"], tg_id))
