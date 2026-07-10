"""Управление пользователями — списки, верификация.

FIX: добавлено логирование ошибок доставки.
FIX v8: логирование ошибок управления пользователями.
        Используется safe_send из services.safe_send.
        Валидация user_id через validation.py.
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import repositories.user_list_repo as user_list_repo
import repositories.user_repo as user_repo
from data.constants import EMOJI, Admin, Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin
from services.safe_send import safe_send
from services.validation import validate_user_id

router = Router()
log = logging.getLogger("iskra.admin.users")


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.USERS.value}")
async def cb_users(call: CallbackQuery) -> None:
    """Показывает последних пользователей."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)

    try:
        from repositories.settings_repo import admin_recent_users
        users = await admin_recent_users(limit=Admin.RECENT_USERS_LIMIT)
    except Exception as e:
        log.error("Failed to load recent users for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки пользователей", show_alert=True)
        return

    if not users:
        return await call.message.edit_text("Пользователей пока нет.", reply_markup=back_kb())

    lines = [f"{EMOJI.PROFILE} <b>Последние {Admin.RECENT_USERS_LIMIT} пользователей:</b>"]
    for u in users:
        status = f"{EMOJI.BANNED}" if u["is_banned"] else (f"{EMOJI.ACTIVE}" if u["active"] else f"{EMOJI.INACTIVE}")
        uname = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        lines.append(f"{status} <b>{u['name']}</b>, {u['age']} — {uname}")
    await safe_send(
        call.message.edit_text("\n".join(lines), reply_markup=back_kb()),
        log_prefix="users_list",
    )
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.VERIFIED.value}")
async def cb_verified(call: CallbackQuery) -> None:
    """Показывает верифицированных пользователей."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)

    try:
        rows = await user_list_repo.get_verified_users(limit=Admin.RECENT_USERS_LIMIT)
    except Exception as e:
        log.error("Failed to load verified users for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки верифицированных", show_alert=True)
        return

    if not rows:
        return await call.message.edit_text(
            f"{EMOJI.VERIFIED} Верифицированных пользователей пока нет.", reply_markup=back_kb()
        )

    tg_ids = [r["tg_id"] for r in rows]
    try:
        names_map = await user_repo.get_user_names_batch(tg_ids)
    except Exception as e:
        log.error("Failed to load user names for verified: %s", e)
        names_map = {}

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
    await safe_send(
        call.message.edit_text("\n".join(lines), reply_markup=kb),
        log_prefix="verified_list",
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.UNVERIFY.value}:"))
async def cb_do_unverify(call: CallbackQuery) -> None:
    """Снимает верификацию."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for unverify: %s", tg_id, e)
        await call.answer(Msg.USER_NOT_FOUND, show_alert=True)
        return

    if not user:
        return await call.answer(Msg.USER_NOT_FOUND)

    try:
        await user_repo.upsert_user(tg_id, verified=0)
    except Exception as e:
        log.error("Failed to unverify user %d: %s", tg_id, e)
        await call.answer("Ошибка снятия верификации", show_alert=True)
        return

    await call.answer(f"{EMOJI.VERIFIED} Верификация снята у {user['name']}")
    await safe_send(
        call.bot.send_message(tg_id, Msg.VERIFICATION_REMOVED),
        log_prefix=f"unverify_notify_{tg_id}",
    )
    await cb_verified(call)


@router.message(Command(Cmd.UNVERIFY.value[1:]))
async def cmd_unverify(message: Message) -> None:
    """Команда снятия верификации."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer(Format.UNVERIFY_USAGE)
    tg_id = validate_user_id(parts[1])
    if tg_id is None:
        return await message.answer(Format.UNVERIFY_USAGE)

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for unverify: %s", tg_id, e)
        await message.answer(Msg.USER_NOT_FOUND)
        return

    if not user:
        return await message.answer(Msg.USER_NOT_FOUND)

    try:
        await user_repo.upsert_user(tg_id, verified=0)
    except Exception as e:
        log.error("Failed to unverify user %d: %s", tg_id, e)
        await message.answer("Ошибка снятия верификации 😕")
        return

    await message.answer(Format.UNVERIFY_SUCCESS.format(user["name"], tg_id))
    await safe_send(
        message.bot.send_message(tg_id, Msg.VERIFICATION_REMOVED),
        log_prefix=f"unverify_cmd_notify_{tg_id}",
    )
        log.error("Failed to load recent users for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки пользователей", show_alert=True)
        return

    if not users:
        return await call.message.edit_text("Пользователей пока нет.", reply_markup=back_kb())

    lines = [f"{EMOJI.PROFILE} <b>Последние {Admin.RECENT_USERS_LIMIT} пользователей:</b>"]
    for u in users:
        status = f"{EMOJI.BANNED}" if u["is_banned"] else (f"{EMOJI.ACTIVE}" if u["active"] else f"{EMOJI.INACTIVE}")
        uname = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        lines.append(f"{status} <b>{u['name']}</b>, {u['age']} — {uname}")
    await safe_send(
        call.message.edit_text("
".join(lines), reply_markup=back_kb()),
        log_prefix="users_list",
    )
    await call.answer()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.VERIFIED.value}")
async def cb_verified(call: CallbackQuery) -> None:
    """Показывает верифицированных пользователей."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)

    try:
        rows = await user_list_repo.get_verified_users(limit=Admin.RECENT_USERS_LIMIT)
    except Exception as e:
        log.error("Failed to load verified users for admin %d: %s", call.from_user.id, e)
        await call.answer("Ошибка загрузки верифицированных", show_alert=True)
        return

    if not rows:
        return await call.message.edit_text(
            f"{EMOJI.VERIFIED} Верифицированных пользователей пока нет.", reply_markup=back_kb()
        )

    tg_ids = [r["tg_id"] for r in rows]
    try:
        names_map = await user_repo.get_user_names_batch(tg_ids)
    except Exception as e:
        log.error("Failed to load user names for verified: %s", e)
        names_map = {}

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
    lines.append(f"
Или: <code>{Cmd.UNVERIFY.value} 123456789</code>")
    buttons.append([InlineKeyboardButton(text=f"{EMOJI.BACK} Назад", callback_data=CallbackPrefix.ADMIN.with_param(AdminAction.MENU.value))])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_send(
        call.message.edit_text("
".join(lines), reply_markup=kb),
        log_prefix="verified_list",
    )
    await call.answer()


@router.callback_query(F.data.startswith(f"{CallbackPrefix.ADMIN.value}:{AdminAction.UNVERIFY.value}:"))
async def cb_do_unverify(call: CallbackQuery) -> None:
    """Снимает верификацию."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    tg_id = int(call.data.split(":")[2])

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for unverify: %s", tg_id, e)
        await call.answer(Msg.USER_NOT_FOUND, show_alert=True)
        return

    if not user:
        return await call.answer(Msg.USER_NOT_FOUND)

    try:
        await user_repo.upsert_user(tg_id, verified=0)
    except Exception as e:
        log.error("Failed to unverify user %d: %s", tg_id, e)
        await call.answer("Ошибка снятия верификации", show_alert=True)
        return

    await call.answer(f"{EMOJI.VERIFIED} Верификация снята у {user['name']}")
    await safe_send(
        call.bot.send_message(tg_id, Msg.VERIFICATION_REMOVED),
        log_prefix=f"unverify_notify_{tg_id}",
    )
    await cb_verified(call)


@router.message(Command(Cmd.UNVERIFY.value[1:]))
async def cmd_unverify(message: Message) -> None:
    """Команда снятия верификации."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer(Format.UNVERIFY_USAGE)
    tg_id = validate_user_id(parts[1])
    if tg_id is None:
        return await message.answer(Format.UNVERIFY_USAGE)

    try:
        user = await user_repo.get_user(tg_id)
    except Exception as e:
        log.error("Failed to load user %d for unverify: %s", tg_id, e)
        await message.answer(Msg.USER_NOT_FOUND)
        return

    if not user:
        return await message.answer(Msg.USER_NOT_FOUND)

    try:
        await user_repo.upsert_user(tg_id, verified=0)
    except Exception as e:
        log.error("Failed to unverify user %d: %s", tg_id, e)
        await message.answer("Ошибка снятия верификации 😕")
        return

    await message.answer(Format.UNVERIFY_SUCCESS.format(user["name"], tg_id))
    await safe_send(
        message.bot.send_message(tg_id, Msg.VERIFICATION_REMOVED),
        log_prefix=f"unverify_cmd_notify_{tg_id}",
    )
