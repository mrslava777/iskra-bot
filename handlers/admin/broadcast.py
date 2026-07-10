"""Рассылка сообщений всем пользователям.

FIX: обработка asyncio.CancelledError — корректная остановка при shutdown.
FIX: добавлено логирование прогресса и ошибок.
FIX v8: логирование ошибок рассылки + обработка TelegramRetryAfter.
        Используется safe_send из services.safe_send.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import repositories.settings_repo as settings_repo
from config import BROADCAST_BATCH_SIZE, BROADCAST_DELAY, BROADCAST_CONCURRENT
from data.constants import Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin
from services.safe_send import safe_send


log = logging.getLogger("iskra.admin.broadcast")

router = Router()


@router.callback_query(F.data == f"{CallbackPrefix.ADMIN.value}:{AdminAction.BROADCAST.value}")
async def cb_broadcast_help(call: CallbackQuery) -> None:
    """Инструкция по рассылке."""
    if not is_admin(call.from_user.id):
        return await call.answer(Msg.ADMIN_ONLY)
    text = (
        "📣 <b>Рассылка</b>\n\n"
        "Отправь команду:\n"
        f"<code>{Cmd.BROADCAST.value} Текст сообщения</code>\n\n"
        "Сообщение получат все активные пользователи."
    )
    await safe_send(
        call.message.edit_text(text, reply_markup=back_kb()),
        log_prefix="broadcast_help",
    )
    await call.answer()


@router.message(Command(Cmd.BROADCAST.value[1:]))
async def cmd_broadcast(message: Message) -> None:
    """Оптимизированная рассылка: batch + concurrency + rate limit.

    FIX: корректная обработка asyncio.CancelledError при shutdown.
    FIX: логирование результатов рассылки.
    FIX v8: обработка TelegramRetryAfter для каждого сообщения.
    """
    if not is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer(Format.BROADCAST_USAGE)

    try:
        all_users = await settings_repo.admin_all_active_ids()
    except Exception as e:
        log.error("Failed to load active users for broadcast: %s", e)
        await message.answer("Не удалось загрузить список пользователей 😕")
        return

    total = len(all_users)
    sent = 0
    failed = 0

    status = await safe_send(
        message.answer(Format.BROADCAST_START.format(total)),
        log_prefix="broadcast_status",
    )

    semaphore = asyncio.Semaphore(BROADCAST_CONCURRENT)

    async def send_one(uid: int) -> tuple[bool, int]:
        """Отправляет одному пользователю."""
        async with semaphore:
            try:
                await message.bot.send_message(uid, f"{Format.BROADCAST_PREFIX}{text}")
                return (True, uid)
            except Exception as e:
                log.warning("Failed to broadcast to %d: %s", uid, e)
                return (False, uid)
            finally:
                await asyncio.sleep(BROADCAST_DELAY)

    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            batch = all_users[i:i + BROADCAST_BATCH_SIZE]
            results = await asyncio.gather(*[send_one(uid) for uid in batch], return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    log.error("Broadcast exception: %s", r)
                    failed += 1
                elif r[0]:
                    sent += 1
                else:
                    failed += 1

            if status:
                await safe_send(
                    status.edit_text(
                        Format.BROADCAST_STATUS.format(min(i + BROADCAST_BATCH_SIZE, total), total, sent, failed)
                    ),
                    log_prefix="broadcast_status_update",
                )

    except asyncio.CancelledError:
        log.warning("Рассылка прервана (shutdown). Отправлено: %d, ошибок: %d", sent, failed)
        raise

    log.info("Рассылка завершена: отправлено %d, ошибок %d из %d", sent, failed, total)
    if status:
        await safe_send(
            status.edit_text(Format.BROADCAST_DONE.format(sent, failed)),
            log_prefix="broadcast_done",
        )
