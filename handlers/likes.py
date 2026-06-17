"""Входящие симпатии и список мэтчей."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import MAIN_MENU, like_response_kb
from services.matching import gender_emoji, profile_caption
from handlers.browse import _announce_match

router = Router()


@router.message(F.text == "💌 Кто меня лайкнул")
async def show_incoming(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — /start.")
        return
    rows = await db.incoming_likes(message.from_user.id)
    if not rows:
        await message.answer(
            "Пока никто не лайкнул 😅 Активность повышает шансы — листай ленту!",
            reply_markup=MAIN_MENU,
        )
        return
    await message.answer(f"💌 Тебя лайкнули: <b>{len(rows)}</b>. Показываю по одному:")
    first = rows[0]
    caption = profile_caption(first, viewer=user, show_compat=True)
    try:
        await message.answer_photo(
            photo=first["photo_id"], caption=caption,
            reply_markup=like_response_kb(first["tg_id"]),
        )
    except Exception:
        await message.answer(caption, reply_markup=like_response_kb(first["tg_id"]))


async def _show_next_incoming(message: Message, viewer_id: int) -> None:
    user = await db.get_user(viewer_id)
    rows = await db.incoming_likes(viewer_id)
    if not rows:
        await message.answer("Это были все входящие симпатии ✨", reply_markup=MAIN_MENU)
        return
    nxt = rows[0]
    caption = profile_caption(nxt, viewer=user, show_compat=True)
    try:
        await message.answer_photo(
            photo=nxt["photo_id"], caption=caption,
            reply_markup=like_response_kb(nxt["tg_id"]),
        )
    except Exception:
        await message.answer(caption, reply_markup=like_response_kb(nxt["tg_id"]))


@router.callback_query(F.data.startswith("lk:"))
async def on_like_back(call: CallbackQuery, bot: Bot) -> None:
    _, decision, uid = call.data.split(":")
    target_id = int(uid)
    viewer_id = call.from_user.id
    await call.message.edit_reply_markup(reply_markup=None)

    if decision == "yes":
        matched = await db.add_like(viewer_id, target_id, True)
        if matched:
            await _announce_match(bot, viewer_id, target_id)
            await call.answer("🎉 Мэтч!")
        else:
            await call.answer("❤️")
    else:
        await db.add_like(viewer_id, target_id, False)
        await call.answer("👎")

    await _show_next_incoming(call.message, viewer_id)


@router.message(F.text == "💞 Мэтчи")
async def show_matches(message: Message) -> None:
    rows = await db.get_matches(message.from_user.id)
    if not rows:
        await message.answer(
            "Мэтчей пока нет 💔 Но всё впереди! Листай анкеты 🔍", reply_markup=MAIN_MENU
        )
        return
    viewer = await db.get_user(message.from_user.id)
    await message.answer(f"💞 <b>Твои мэтчи ({len(rows)}):</b>")
    for r in rows:
        if r["username"]:
            contact = f"@{r['username']}"
        else:
            contact = f'<a href="tg://user?id={r["tg_id"]}">{r["name"]}</a>'
        caption = profile_caption(r, viewer=viewer, show_compat=True)
        caption += f"\n\n📨 Контакт: {contact}"
        try:
            await message.answer_photo(
                photo=r["photo_id"], caption=caption,
            )
        except Exception:
            await message.answer(caption)
    await message.answer("Это все твои мэтчи ✨", reply_markup=MAIN_MENU)
