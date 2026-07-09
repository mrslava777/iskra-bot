"""Рассылка сообщений всем пользователям.

FIX: обработка asyncio.CancelledError — корректная остановка при shutdown.
FIX: добавлено логирование прогресса и ошибок.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import repositories.settings_repo as settings_repo
from config import BROADCAST_BATCH_SIZE, BROADCAST_DELAY, BROADCAST_CONCURRENT
from data.constants import Message as Msg, Format
from data.enums import AdminAction, CallbackPrefix, Command as Cmd
from keyboards import back_kb
from services.admin_service import is_admin


log = logging.getLogger("iskra." + __name__.split(".")[-1])

async def _safe_send(coro, fallback=None):
    """Safe wrapper for Telegram send operations."""
    try:
        return await coro
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception:
            pass
    except TelegramForbiddenError:
        pass
    except Exception:
        if fallback:
            try:
                return await fallback
            except Exception:
                pass
    return None

router = Router()
log = logging.getLogger("iskra.broadcast")


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
    await call.message.edit_text(text, reply_markup=back_kb())


@router.message(Command(Cmd.BROADCAST.value[1:]))
async def cmd_broadcast(message: Message) -> None:
    """Оптимизированная рассылка: batch + concurrency + rate limit.

    FIX: корректная обработка asyncio.CancelledError при shutdown.
    FIX: логирование результатов рассылки.
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
    semaphore = asyncio.Semaphore(BROADCAST_CONCURRENT)

    async def send_one(uid: int) -> tuple[bool, int]:
        """Отправляет одному пользователю."""
        async with semaphore:
            try:
                await message.bot.send_message(uid, f"{Format.BROADCAST_PREFIX}{text}")
                result = (True, uid)
            except Exception:
                result = (False, uid)
            await asyncio.sleep(BROADCAST_DELAY)
            return result

    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            batch = all_users[i:i + BROADCAST_BATCH_SIZE]
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
                    Format.BROADCAST_STATUS.format(min(i + BROADCAST_BATCH_SIZE, total), total, sent, failed)
                )
            except Exception:
                pass

    except asyncio.CancelledError:
        log.warning("Рассылка прервана (shutdown). Отправлено: %d, ошибок: %d", sent, failed)
        raise

    log.info("Рассылка завершена: отправлено %d, ошибок %d из %d", sent, failed, total)
    await status.edit_text(Format.BROADCAST_DONE.format(sent, failed))
