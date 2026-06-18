"""Поддержка пользователей — меню категорий + пересылка тикетов админам."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from config import ADMIN_IDS
from keyboards import MAIN_MENU, support_kb
from states import Support

router = Router()

CATEGORIES = {
    "report": ("🧧 Жалоба на пользователя", "опасное поведение, нарушения"),
    "rights": ("🗣 Нарушение моих прав", "используют мои данные"),
    "other": ("❓ Другое", "вопросы, лагает/не работает, верификация, юр. запросы"),
}

SUPPORT_INTRO = (
    "📩 <b>Поддержка</b>\n\n"
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
        f"{label}\n\n"
        "Опишите вашу проблему одним сообщением.\n"
        "Можете прикрепить скриншот 📷\n\n"
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

    ticket_text = (
        f"📩 <b>Тикет поддержки</b>\n\n"
        f"<b>Категория:</b> {cat_label}\n"
        f"<b>Пользователь:</b> {name} ({username})\n"
        f"<b>ID:</b> <code>{uid}</code>\n\n"
        f"<b>Сообщение:</b>\n{text[:1000]}"
    )

    sent_count = 0
    for admin_id in ADMIN_IDS:
        try:
            if photo_id:
                await message.bot.send_photo(
                    admin_id, photo=photo_id, caption=ticket_text,
                )
            else:
                await message.bot.send_message(admin_id, text=ticket_text)
            sent_count += 1
        except Exception:
            pass

    await message.answer(
        "✅ <b>Обращение отправлено!</b>\n\n"
        "Администратор рассмотрит его в ближайшее время. "
        "Ответ придёт в этот чат.",
        reply_markup=MAIN_MENU,
    )
