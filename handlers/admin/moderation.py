"""Модерация — бан, разбан, жалобы.

FIX v8: логирование ошибок бана/разбана.
NEW: раздел «Жалобы» показывает статус цели (активна / скрыта / забанена),
 чтобы было видно, сработал ли порог автоскрытия. Для скрытых/забаненных
 добавлена кнопка «Вернуть» (разбан + возврат в ленту).
"""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.settings_repo as settings_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, Admin, Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin
from services.safe_send import safe_send
from services.validation import validate_user_id

router = Router()
log = logging.getLogger("iskra.admin.moderation")


def _status_label(active, is_banned) -> str:
    """Человекочитаемый статус анкеты для списка жалоб."""
    if is_banned:
        return f"{EMOJI.BANNED} забанен"
    if not active:
        return f"{EMOJI.INACTIVE} скрыт"
    return f"{EMOJI.ACTIVE} активен"


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BAN.value}")
async def cb_ban_help(call: CallbackQuery) -> None:
    """Инструкция по бану."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    text = (
        f"{EMOJI.REPORT} Бан / Разбан \n"
        "Отправь команду:\n"
        f" {Cmd.BAN.value} 123456789 — забанить\n"
        f" {Cmd.UNBAN.value} 123456789 — разбанить\n"
        "Или нажми кнопку в разделе «Жалобы»."
    )
    await safe_send(
        call.message.edit_text(text, reply_markup=back_kb()),
        log_prefix="ban_help",
    )
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.REPORTS.value}")
async def cb_reports(call: CallbackQuery) -> None:
    """Показывает последние жалобы со статусом цели."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    try:
        reports = await settings_repo.admin_recent_reports(limit=Admin.RECENT_REPORTS_LIMIT)
    except Exception as e:
        log.error("Failed to load reports for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки жалоб", show_alert=True)
        return

    if not reports:
        return await call.message.edit_text(f"{EMOJI.REPORT} Жалоб нет 🎉", reply_markup=back_kb())

    target_ids = list(set(r["to_id"] for r in reports))
    try:
        users_map = await user_repo.get_user_names_batch(target_ids)
    except Exception as e:
        log.error("Failed to load user names for reports: %s", e)
        users_map = {}

    lines = [f"{EMOJI.REPORT} Последние жалобы: "]
    buttons = []
    for r in reports:
        target_id = r["to_id"]
        name = users_map.get(target_id, "удалён")
        status = _status_label(r.get("active"), r.get("is_banned"))
        lines.append(f"• {name} (ID: {target_id}) — {r['report_count']} жалоб(ы) · {status}")

        # Кнопка зависит от текущего статуса.
        if r.get("is_banned"):
            buttons.append([
                InlineKeyboardButton(
                    text=f"{EMOJI.ACTIVE} Вернуть {target_id}",
                    callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.DO_UNBAN.value, target_id),
                )
            ])
        elif not r.get("active"):
            # Скрыт автоскрытием: можно вернуть в ленту или добить баном.
            buttons.append([
                InlineKeyboardButton(
                    text=f"{EMOJI.ACTIVE} Вернуть {target_id}",
                    callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.DO_UNBAN.value, target_id),
                ),
                InlineKeyboardButton(
                    text=f"{EMOJI.BANNED} Бан {target_id}",
                    callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.DO_BAN.value, target_id),
                ),
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{EMOJI.REPORT} Бан {target_id}",
                    callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.DO_BAN.value, target_id),
                )
            ])

    buttons.append([InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.MENU.value))])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_send(
        call.message.edit_text("\n".join(lines), reply_markup=kb),
        log_prefix="reports",
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.DO_BAN.value}:"))
async def cb_do_ban(call: CallbackQuery) -> None:
    """Банит пользователя из списка жалоб."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])
    try:
        await settings_repo.admin_ban_user(tg_id)
    except Exception as e:
        log.error("Failed to ban user %d: %s", tg_id, e)
        await call.answer("Ошибка бана 😕", show_alert=True)
        return

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d after ban: %s", tg_id, e)
        user = None

    name = user["name"] if user else "?"
    await call.answer(f"{EMOJI.VERIFIED} {name} забанен")
    await cb_reports(call)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.DO_UNBAN.value}:"))
async def cb_do_unban(call: CallbackQuery) -> None:
    """Возвращает пользователя в ленту из списка жалоб (разбан + active=1)."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])
    try:
        await settings_repo.admin_unban_user(tg_id)
    except Exception as e:
        log.error("Failed to unban user %d: %s", tg_id, e)
        await call.answer("Ошибка возврата 😕", show_alert=True)
        return

    try:
        user = await user_repo.get_user(tg_id)
    except Exception:
        user = None
    name = user["name"] if user else "?"
    await call.answer(f"{EMOJI.ACTIVE} {name} возвращён в ленту")
    await cb_reports(call)


@router.message(Command(Cmd.BAN.value[1:]))
async def cmd_ban(message: Message) -> None:
    """Команда бана."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer(Format.BAN_USAGE)
    tg_id = validate_user_id(parts[1])
    if tg_id is None:
        return await message.answer(Format.BAN_USAGE)

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for ban: %s", tg_id, e)
        await message.answer(Msg.USER_NOT_FOUND)
        return

    if not user:
        return await message.answer(Msg.USER_NOT_FOUND)

    try:
        await settings_repo.admin_ban_user(tg_id)
    except Exception as e:
        log.error("Failed to ban user %d: %s", tg_id, e)
        await message.answer("Ошибка бана 😕")
        return

    await message.answer(Format.BAN_SUCCESS.format(user["name"], tg_id))


@router.message(Command(Cmd.UNBAN.value[1:]))
async def cmd_unban(message: Message) -> None:
    """Команда разбана."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer(Format.UNBAN_USAGE)
    tg_id = validate_user_id(parts[1])
    if tg_id is None:
        return await message.answer(Format.UNBAN_USAGE)

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for unban: %s", tg_id, e)
        await message.answer(Msg.USER_NOT_FOUND)
        return

    if not user:
        return await message.answer(Msg.USER_NOT_FOUND)

    try:
        await settings_repo.admin_unban_user(tg_id)
    except Exception as e:
        log.error("Failed to unban user %d: %s", tg_id, e)
        await message.answer("Ошибка разбана 😕")
        return

    await message.answer(Format.UNBAN_SUCCESS.format(user["name"], tg_id))
