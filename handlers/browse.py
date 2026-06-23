"""Лента анкет: показ, лайк/дизлайк, мэтчи, жалобы."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from data.content import icebreaker
from keyboards import MAIN_MENU, browse_kb
from services.matching import (
    common_interests,
    compatibility,
    gender_emoji,
    profile_caption,
)

router = Router()


async def show_next(message: Message, viewer_id: int) -> None:
    cand = await db.next_candidate(viewer_id)
    if cand is None:
        await message.answer(
            "Пока новых анкет нет 🙈 Загляни позже или измени фильтры в ⚙️ Настройках.",
            reply_markup=MAIN_MENU,
        )
        return
    viewer = await db.get_user(viewer_id)
    await db.mark_shown(cand["tg_id"])
    caption = profile_caption(cand, viewer=viewer, show_compat=True)
    extra = await db.photo_count(cand["tg_id"]) > 1
    has_voice = bool(cand["voice_id"])
    kb = browse_kb(cand["tg_id"], has_extra_photos=extra, has_voice=has_voice)
    try:
        await message.answer_photo(photo=cand["photo_id"], caption=caption, reply_markup=kb)
    except Exception:
        await message.answer(caption, reply_markup=kb)


@router.message(F.text == "🔍 Смотреть анкеты")
async def start_browse(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("Сначала создай анкету — отправь /start.")
        return
    await db.touch_activity(message.from_user.id)
    await show_next(message, message.from_user.id)


@router.callback_query(F.data.startswith("sw:"))
async def on_swipe(call: CallbackQuery, bot: Bot) -> None:
    parts = call.data.split(":")
    action = parts[1]
    viewer_id = call.from_user.id

    if action == "stop":
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(
            "Остановились ⏹ Возвращайся в любой момент!", reply_markup=MAIN_MENU
        )
        await call.answer()
        return

    target_id = int(parts[2])
    await call.message.edit_reply_markup(reply_markup=None)

    if action == "photos":
        photos = await db.get_photos(target_id)
        extras = [p for p in photos if p["position"] > 0]
        if extras:
            from aiogram.types import InputMediaPhoto
            media = [InputMediaPhoto(media=p["photo_id"]) for p in extras]
            try:
                await call.message.answer_media_group(media)
            except Exception:
                pass
        else:
            await call.answer("Нет дополнительных фото")
        await call.answer()
        return

    # NEW: прослушать голосовое
    if action == "voice":
        target = await db.get_user(target_id)
        if target and target["voice_id"]:
            try:
                await call.message.answer_voice(
                    voice=target["voice_id"],
                    caption=f"🎙 Голосовое от {target['name']}, {target['age']} {gender_emoji(target['gender'])}",
                )
            except Exception:
                await call.answer("Не удалось отправить голосовое")
        else:
            await call.answer("Голосовое недоступно")
        await call.answer()
        return

    if action == "report":
        await db.add_report(viewer_id, target_id)
        await call.answer("Спасибо, жалоба отправлена 🚩")
        await show_next(call.message, viewer_id)
        return

    is_like = action in ("like", "msglike")
    matched = await db.add_like(viewer_id, target_id, is_like)

    if is_like:
        await _notify_liked(bot, viewer_id, target_id, with_message=(action == "msglike"))
    if matched:
        await _announce_match(bot, viewer_id, target_id)

    await call.answer("❤️" if is_like else "👎")
    await show_next(call.message, viewer_id)


async def _notify_liked(bot: Bot, from_id: int, to_id: int, with_message: bool) -> None:
    target = await db.get_user(to_id)
    if not target or not target["active"] or target["is_banned"]:
        return
    me = await db.get_user(from_id)
    if not me:
        return
    pct = compatibility(me["interests"], target["interests"])
    text = (
        "💌 Кто-то проявил симпатию!\n"
        f"Совместимость с этим человеком — <b>{pct}%</b>.\n"
    )
    if with_message:
        text += f"\n💬 Подсказка для первого сообщения:\n<i>{icebreaker(from_id + to_id)}</i>\n"
    text += "\nОткрой «💌 Кто меня лайкнул», чтобы посмотреть анкету."
    try:
        await bot.send_message(to_id, text)
    except Exception:
        pass


async def _announce_match(bot: Bot, a_id: int, b_id: int) -> None:
    a = await db.get_user(a_id)
    b = await db.get_user(b_id)
    if not a or not b:
        return
    ice = icebreaker(a_id + b_id)
    for me, other in ((a, b), (b, a)):
        common = common_interests(a["interests"], b["interests"])
        common_txt = ("\n🏷 Общее: " + ", ".join(common)) if common else ""
        if other["username"]:
            contact = f"@{other['username']}"
        else:
            contact = f'<a href="tg://user?id={other["tg_id"]}">{other["name"]}</a>'
        text = (
            f"🎉 <b>Это мэтч!</b> {gender_emoji(other['gender'])}\n\n"
            f"Вы понравились друг другу с <b>{other['name']}</b>, {other['age']}."
            f"{common_txt}\n\n"
            f"📨 Контакт: {contact}\n\n"
            f"💬 С чего начать:\n<i>{ice}</i>"
        )
        try:
            await bot.send_photo(me["tg_id"], photo=other["photo_id"], caption=text)
        except Exception:
            try:
                await bot.send_message(me["tg_id"], text)
            except Exception:
                pass
