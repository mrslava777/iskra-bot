"""Управление пользователями — списки, верификация."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.user_list_repo as user_list_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, Admin, Message, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.USERS.value}")
async def cb_users(call: CallbackQuery) -> None:
    """Показывает последних пользователей."""
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    from repositories.settings_repo import admin_recent_users
    users = await admin_recent_users(limit=Admin.RECENT_USERS_LIMIT)
    if not users:
        return await call.message.edit_text("Пользователей пока нет.", reply_markup=back_kb())

    lines = [f"{EMOJI.PROFILE} <b>Последние {Admin.RECENT_USERS_LIMIT} пользователей:</b>"]
    for u in users:
        status = f"{EMOJI.BANNED}" if u["is_banned"] else (f"{EMOJI.ACTIVE}" if u["active"] else f"{EMOJI.INACTIVE}")
        uname = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        lines.append(f"{status} <b>{u['name']}</b>, {u['age']} — {uname}")
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb())


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.VERIFIED.value}")
async def cb_verified(call: CallbackQuery) -> None:
    """Показывает верифицированных пользователей.

    Оптимизация: batch-запрос для имён вместо N запросов get_user.
    """
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    rows = await user_list_repo.get_verified_users(limit=Admin.RECENT_USERS_LIMIT)
    if not rows:
        return await call.message.edit_text(
            f"{EMOJI.VERIFIED} Верифицированных пользователей пока нет.", reply_markup=back_kb()
        )

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    tg_ids = [r["tg_id"] for r in rows]
    names_map = await user_repo.get_user_names_batch(tg_ids)

    lines = [f"{EMOJI.VERIFIED} <b>Верифицированные пользователи:</b>"]
    buttons = []
    for r in rows:
        uname = f"@{r['username']}" if r["username"] else f"ID:{r['tg_id']}"
        lines.append(f"• <b>{r['name']}</b> — {uname}")
        buttons.append([
            InlineKeyboardButton(
                text=f"{EMOJI.DISLIKE} Снять верификацию — {r['name']}",
                callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.UNVERIFY.value, r["tg_id"]),
            )
        ])
    lines.append(f"\nИли: <code>{Cmd.UNVERIFY.value} 123456789</code>")
    buttons.append([InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.MENU.value))])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.UNVERIFY.value}:"))
async def cb_do_unverify(call: CallbackQuery) -> None:
    """Снимает верификацию."""
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])
    user = await user_repo.get_user(tg_id)
    if not user:
        return await call.answer(Message.USER_NOT_FOUND)
    await user_repo.upsert_user(tg_id, verified=0)
    await call.answer(f"{EMOJI.VERIFIED} Верификация снята у {user['name']}")
    try:
        await call.bot.send_message(tg_id, Message.VERIFICATION_REMOVED)
    except Exception:
        pass
    await cb_verified(call)


@router.message(Command(Cmd.UNVERIFY.value[1:]))
async def cmd_unverify(message: Message) -> None:
    """Команда снятия верификации."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer(Format.UNVERIFY_USAGE)
    tg_id = int(parts[1])
    user = await user_repo.get_user(tg_id)
    if not user:
        return await message.answer(Message.USER_NOT_FOUND)
    await user_repo.upsert_user(tg_id, verified=0)
    await message.answer(Format.UNVERIFY_SUCCESS.format(user["name"], tg_id))
    try:
        await message.bot.send_message(tg_id, Message.VERIFICATION_REMOVED)
    except Exception:
        pass
