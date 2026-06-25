"""Поддержка пользователей — меню категорий + тикеты админам + ответ."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from config import ADMIN_IDS
from keyboards import MAIN_MENU, support_kb, support_reply_kb
from states import Support

router = Router()

CATEGORIES = {
    "report": ("🧧 Жалоба на пользователя", "опасное поведение, нарушения"),
    "rights": ("🗣 Нарушение моих прав", "используют мои данные"),
    "other": ("❓ Другое", "вопросы, лагает/не работает, верификация, юр. запросы"),
}

SUPPORT_INTRO = (
    "📩 <b>Поддержка</b>

"
    "С чем у вас возникла проблема?"
)


@router.message(Command("support"))
@router.message(F.text == "📩 Поддержка")
async def cmd_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(SUPPORT_INTRO, reply_markup=support_kb())


@router.callback_query(F.data.startswith("sup:"))
async def on_support_category(call: CallbackQuery, state: FSMContext) -> None:
    cat = call.data.split(":")[1]
    if cat not in CATEGORIES:
        await call.answer("Неизвестная категория")
        return
    label, _ = CATEGORIES[cat]
    await state.update_data(support_cat=cat, support_label=label)
    await state.set_state(Support.message)
    await call.message.edit_text(
        f"{label}

"
        "Опишите вашу проблему одним сообщением.
"
        "Можете прикрепить скриншот 📷

"
        "Для отмены — /cancel"
    )
    await call.answer()


@router.message(Support.message, Command("cancel"))
async def support_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("↩️ Обращение отменено.", reply_markup=MAIN_MENU)


@router.message(Support.message, F.text)
async def support_text(message: Message, state: FSMContext) -> None:
    await _process_ticket(message, state, text=message.text.strip())


@router.message(Support.message, F.photo)
async def support_photo(message: Message, state: FSMContext) -> None:
    await _process_ticket(
        message, state,
        text=message.caption.strip() if message.caption else "(фото без описания)",
        photo_id=message.photo[-1].file_id,
    )


@router.message(Support.message)
async def support_invalid(message: Message) -> None:
    await message.answer("Отправьте текст или фото с описанием проблемы.")


async def _process_ticket(
    message: Message, state: FSMContext,
    text: str, photo_id: str | None = None,
) -> None:
    data = await state.get_data()
    cat_label = data.get("support_label", "❓")
    cat_key = data.get("support_cat", "other")
    await state.clear()

    user = await db.get_user(message.from_user.id)
    name = user["name"] if user else "?"
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    uid = message.from_user.id

    # Save ticket to DB
    ticket_id = await db.create_ticket(uid, cat_key, text[:1000], photo_id)

    ticket_text = (
        f"📩 <b>Тикет #{ticket_id}</b>

"
        f"<b>Категория:</b> {cat_label}
"
        f"<b>Пользователь:</b> {name} ({username})
"
        f"<b>ID:</b> <code>{uid}</code>

"
        f"<b>Сообщение:</b>
{text[:1000]}"
    )

    for admin_id in ADMIN_IDS:
        try:
            if photo_id:
                await message.bot.send_photo(
                    admin_id, photo=photo_id, caption=ticket_text,
                    reply_markup=support_reply_kb(uid, ticket_id),
                )
            else:
                await message.bot.send_message(
                    admin_id, text=ticket_text,
                    reply_markup=support_reply_kb(uid, ticket_id),
                )
        except Exception:
            pass

    await message.answer(
        "✅ <b>Обращение отправлено!</b>

"
        "Администратор рассмотрит его в ближайшее время. "
        "Ответ придёт в этот чат.",
        reply_markup=MAIN_MENU,
    )


# ---------- Ответ админа (из Telegram) ----------

@router.callback_query(F.data.startswith("supreply:"))
async def on_admin_reply(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Только для админов", show_alert=True)
        return
    parts = call.data.split(":")
    tg_id = int(parts[1])
    ticket_id = int(parts[2]) if len(parts) > 2 else None
    await state.update_data(reply_to_user=tg_id, reply_ticket_id=ticket_id)
    await state.set_state(Support.admin_reply)
    await call.message.answer(
        f"✏️ Напиши ответ пользователю <code>{tg_id}</code>:
"
        "(или /cancel для отмены)"
    )
    await call.answer()


@router.message(Support.admin_reply, Command("cancel"))
async def admin_reply_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("↩️ Ответ отменён.")


@router.message(Support.admin_reply, F.text)
async def admin_reply_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tg_id = data.get("reply_to_user")
    if not tg_id:
        await state.clear()
        return
    ticket_id = data.get("reply_ticket_id")
    reply_text = message.text.strip()
    await state.clear()
    try:
        await message.bot.send_message(
            tg_id,
            f"💬 <b>Ответ от поддержки:</b>

{reply_text}",
        )
        # Обновляем статус тикета в БД → 'replied'
        if ticket_id:
            await db.reply_ticket(ticket_id, reply_text)
        await message.answer(f"✅ Ответ отправлен пользователю {tg_id}.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")
