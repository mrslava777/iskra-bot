"""Рассылка сообщений всем пользователям."""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.settings_repo as settings_repo
from data.constants import Broadcast, Message, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BROADCAST.value}")
async def cb_broadcast_help(call: CallbackQuery) -> None:
    """Инструкция по рассылке."""
    if not is_admin(call.from_user.id):
        return await call.answer(Message.ADMIN_ONLY)
    text = (
        "📣 <b>Рассылка</b>\n\n"
        "Отправь команду:\n"
        f"<code>{Cmd.BROADCAST.value} Текст сообщения</code>\n\n"
        "Сообщение получат все активные пользователи."
    )
    await call.message.edit_text(text, reply_markup=back_kb())


@router.message(Command(Cmd.BROADCAST.value[1:]))
async def cmd_broadcast(message: Message) -> None:
    """Оптимизированная рассылка: batch + concurrency + rate limit.

    Оптимизации:
    1. Убран мёртвый asyncio.sleep после return в send_one
    2. sleep перенесён внутрь semaphore, перед return
    3. gather с return_exceptions=True обрабатывается корректно
    """
    if not is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer(Format.BROADCAST_USAGE)

    all_users = await settings_repo.admin_all_active_ids()
    total = len(all_users)
    sent = 0
    failed = 0

    status = await message.answer(Format.BROADCAST_START.format(total))
    semaphore = asyncio.Semaphore(Broadcast.CONCURRENT)

    async def send_one(uid: int) -> tuple[bool, int]:
        """Отправляет одному пользователю.

        Оптимизация: sleep внутри semaphore, перед return.
        """
        async with semaphore:
            try:
                await message.bot.send_message(uid, f"{Format.BROADCAST_PREFIX}{text}")
                result = (True, uid)
            except Exception:
                result = (False, uid)
            await asyncio.sleep(Broadcast.DELAY)
            return result

    for i in range(0, total, Broadcast.BATCH_SIZE):
        batch = all_users[i:i + Broadcast.BATCH_SIZE]
        results = await asyncio.gather(*[send_one(uid) for uid in batch], return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                failed += 1
            elif r[0]:
                sent += 1
            else:
                failed += 1

        try:
            await status.edit_text(
                Format.BROADCAST_STATUS.format(min(i + Broadcast.BATCH_SIZE, total), total, sent, failed)
            )
        except Exception:
            pass

    await status.edit_text(Format.BROADCAST_DONE.format(sent, failed))
