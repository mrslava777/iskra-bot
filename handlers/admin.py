"""Админ-панель в Telegram — статистика, жалобы, бан/разбан."""
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import database as db
from ..config import ADMIN_IDS

router = Router()


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


# ── Inline-клавиатуры ──────────────────────────────────────────────
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users")],
            [InlineKeyboardButton(text="🚩 Жалобы", callback_data="adm:reports")],
            [InlineKeyboardButton(text="✅ Верификация", callback_data="adm:verified")],
            [InlineKeyboardButton(text="🏆 Артефакты", callback_data="adm:badges")],
            [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm:ban")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="adm:menu")]
        ]
    )


# ── /admin — главное меню ──────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🛡 <b>Админ-панель Искра</b>\n\nВыбери раздел:",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    await cq.message.edit_text(
        "🛡 <b>Админ-панель Искра</b>\n\nВыбери раздел:",
        reply_markup=admin_menu_kb(),
    )


# ── Статистика ─────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:stats")
async def cb_stats(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    s = await db.stats()
    ext = await db.admin_extended_stats()
    now = int(time.time())
    today_start = now - (now % 86400)

    text = (
        "📊 <b>Статистика Искра</b>\n\n"
        f"👥 Всего пользователей: <b>{s['users']}</b>\n"
        f"🟢 Активных: <b>{s['active']}</b>\n"
        f"🆕 Новых сегодня: <b>{ext['new_today']}</b>\n"
        f"🚫 Забанено: <b>{ext['banned']}</b>\n\n"
        f"❤️ Лайков: <b>{s['likes']}</b>\n"
        f"💞 Мэтчей: <b>{s['matches']}</b>\n"
        f"🚩 Жалоб: <b>{ext['reports']}</b>\n\n"
        f"👨 Парней: <b>{ext['males']}</b>\n"
        f"👩 Девушек: <b>{ext['females']}</b>"
    )
    await cq.message.edit_text(text, reply_markup=back_kb())


# ── Пользователи (последние 20) ───────────────────────────────────
@router.callback_query(F.data == "adm:users")
async def cb_users(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    users = await db.admin_recent_users(limit=20)
    if not users:
        return await cq.message.edit_text(
            "Пользователей пока нет.", reply_markup=back_kb()
        )
    lines = ["👥 <b>Последние 20 пользователей:</b>\n"]
    for u in users:
        status = "🚫" if u["is_banned"] else ("🟢" if u["active"] else "🔴")
        uname = f"@{u['username']}" if u["username"] else f"ID:{u['tg_id']}"
        lines.append(
            f"{status} <b>{u['name']}</b>, {u['age']} — {uname}"
        )
    await cq.message.edit_text("\n".join(lines), reply_markup=back_kb())


# ── Жалобы ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:reports")
async def cb_reports(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    reports = await db.admin_recent_reports(limit=10)
    if not reports:
        return await cq.message.edit_text(
            "🚩 Жалоб нет 🎉", reply_markup=back_kb()
        )
    lines = ["🚩 <b>Последние жалобы:</b>\n"]
    for r in reports:
        target = await db.get_user(r["to_id"])
        name = target["name"] if target else "удалён"
        banned = " 🚫BANNED" if target and target["is_banned"] else ""
        count = r["report_count"]
        lines.append(
            f"• <b>{name}</b> (ID: <code>{r['to_id']}</code>) — "
            f"{count} жалоб(ы){banned}"
        )

    buttons = []
    for r in reports:
        target = await db.get_user(r["to_id"])
        if target and not target["is_banned"]:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🔨 Бан {r['to_id']}",
                        callback_data=f"adm:doban:{r['to_id']}",
                    )
                ]
            )
    buttons.append(
        [InlineKeyboardButton(text="↩️ Назад", callback_data="adm:menu")]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cq.message.edit_text("\n".join(lines), reply_markup=kb)


# ── Артефакты (статистика по значкам) ──────────────────────────────
@router.callback_query(F.data == "adm:badges")
async def cb_badges_stats(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    conn = await db.get_db()

    # Статистика по каждому значку
    from ..data.badges import BADGES, RARITY_EMOJI, rarity_label
    lines = ["🏆 <b>Статистика Артефактов</b>\n"]

    for badge in BADGES:
        cur = await conn.execute(
            "SELECT COUNT(*) c FROM user_badges WHERE badge_id = ?",
            (badge["id"],)
        )
        row = await cur.fetchone()
        count = row["c"] if row else 0
        rarity_emoji = RARITY_EMOJI.get(badge["rarity"], "⚪")
        lines.append(
            f"{badge['icon']} <b>{badge['name']}</b> — {count} чел. "
            f"({rarity_emoji} {rarity_label(badge['rarity'])}"
        )

    # Топ-10 по количеству значков
    cur = await conn.execute(
        """\n        SELECT tg_id, COUNT(*) as cnt FROM user_badges \n        GROUP BY tg_id ORDER BY cnt DESC LIMIT 10\n        """
    )
    top = await cur.fetchall()
    if top:
        lines.append("\n<b>Топ-10 коллекционеров:</b>")
        for i, r in enumerate(top, 1):
            user = await db.get_user(r["tg_id"])
            name = user["name"] if user else f"ID:{r['tg_id']}"
            lines.append(f"{i}. <b>{name}</b> — {r['cnt']} значков")

    await cq.message.edit_text("\n".join(lines), reply_markup=back_kb())


# ── Верификация ────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:verified")
async def cb_verified(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT tg_id, name, username FROM users WHERE verified = 1 ORDER BY created_at DESC LIMIT 20"
    )
    rows = await cur.fetchall()
    if not rows:
        return await cq.message.edit_text(
            "✅ Верифицированных пользователей пока нет.", reply_markup=back_kb()
        )
    lines = ["✅ <b>Верифицированные пользователи:</b>\n"]
    buttons = []
    for r in rows:
        uname = f"@{r['username']}" if r["username"] else f"ID:{r['tg_id']}"
        lines.append(f"• <b>{r['name']}</b> — {uname}")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Снять верификацию — {r['name']}",
                    callback_data=f"adm:unverify:{r['tg_id']}",
                )
            ]
        )
    lines.append(f"\nИли: <code>/unverify 123456789</code>")
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="adm:menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cq.message.edit_text("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("adm:unverify:"))
async def cb_do_unverify(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    tg_id = int(cq.data.split(":")[2])
    user = await db.get_user(tg_id)
    if not user:
        return await cq.answer("❌ Пользователь не найден")
    await db.upsert_user(tg_id, verified=0)
    name = user["name"]
    await cq.answer(f"✅ Верификация снята у {name}")
    try:
        await cq.bot.send_message(tg_id, "ℹ️ Ваша верификация была снята администратором.")
    except Exception:
        pass
    await cb_verified(cq)


# ── Бан / Разбан (инструкция) ──────────────────────────────────────
@router.callback_query(F.data == "adm:ban")
async def cb_ban_help(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    text = (
        "🔨 <b>Бан / Разбан</b>\n\n"
        "Отправь команду:\n"
        "<code>/ban 123456789</code> — забанить\n"
        "<code>/unban 123456789</code> — разбанить\n\n"
        "Или нажми кнопку бана в разделе «Жалобы»."
    )
    await cq.message.edit_text(text, reply_markup=back_kb())


# ── Бан из жалоб ───────────────────────────────────────────────────
@router.callback_query(F.data.startswith("adm:doban:"))
async def cb_do_ban(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    tg_id = int(cq.data.split(":")[2])
    await db.admin_ban_user(tg_id)
    user = await db.get_user(tg_id)
    name = user["name"] if user else "?"
    await cq.answer(f"✅ {name} забанен")
    await cb_reports(cq)


# ── /ban и /unban ──────────────────────────────────────────────────
@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Использование: <code>/ban 123456789</code>")
    tg_id = int(parts[1])
    user = await db.get_user(tg_id)
    if not user:
        return await message.answer("❌ Пользователь не найден.")
    await db.admin_ban_user(tg_id)
    await message.answer(f"🚫 <b>{user['name']}</b> (ID: <code>{tg_id}</code>) забанен.")


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Использование: <code>/unban 123456789</code>")
    tg_id = int(parts[1])
    user = await db.get_user(tg_id)
    if not user:
        return await message.answer("❌ Пользователь не найден.")
    await db.admin_unban_user(tg_id)
    await message.answer(
        f"✅ <b>{user['name']}</b> (ID: <code>{tg_id}</code>) разбанен."
    )


@router.message(Command("unverify"))
async def cmd_unverify(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Использование: <code>/unverify 123456789</code>")
    tg_id = int(parts[1])
    user = await db.get_user(tg_id)
    if not user:
        return await message.answer("❌ Пользователь не найден.")
    await db.upsert_user(tg_id, verified=0)
    await message.answer(
        f"✅ Верификация снята у <b>{user['name']}</b> (ID: <code>{tg_id}</code>)."
    )
    try:
        await message.bot.send_message(tg_id, "ℹ️ Ваша верификация была снята администратором.")
    except Exception:
        pass


# ── Рассылка ───────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast_help(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        return await cq.answer("⛔")
    text = (
        "📣 <b>Рассылка</b>\n\n"
        "Отправь команду:\n"
        "<code>/broadcast Текст сообщения</code>\n\n"
        "Сообщение получат все активные пользователи."
    )
    await cq.message.edit_text(text, reply_markup=back_kb())


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer(
            "Использование: <code>/broadcast Ваше сообщение</code>"
        )
    users = await db.admin_all_active_ids()
    sent = 0
    failed = 0
    status = await message.answer(f"📣 Отправляю {len(users)} пользователям...")
    for uid in users:
        try:
            await message.bot.send_message(uid, f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1
    await status.edit_text(
        f"📣 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: {sent}\n❌ Ошибок: {failed}"
    )
