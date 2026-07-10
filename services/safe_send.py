"""Безопасная отправка сообщений в Telegram с retry и обработкой ошибок.

Единая точка для всех fire-and-forget и retry-отправок.
Используется в хендлерах, сервисах и админ-панели.
"""
import asyncio
import logging
from typing import Any, Awaitable, Optional

from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

log = logging.getLogger("iskra.safe_send")


async def safe_send(
    coro: Awaitable[Any],
    fallback: Optional[Awaitable[Any]] = None,
    log_prefix: str = "",
) -> Any:
    """Безопасно выполняет coroutine с обработкой Telegram-ошибок.

    Args:
        coro: Основная корутина (например, bot.send_message).
        fallback: Запасная корутина, если основная упала.
        log_prefix: Префикс для логов (например, "broadcast" или "match").

    Returns:
        Результат coro/fallback или None при ошибке.
    """
    try:
        return await coro
    except TelegramRetryAfter as e:
        log.warning("%s Rate limit, retry after %s sec", log_prefix, e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            return await coro
        except Exception as e2:
            log.error("%s Retry failed: %s", log_prefix, e2)
    except TelegramForbiddenError:
        log.debug("%s User blocked bot, skipping", log_prefix)
    except Exception as e:
        log.warning("%s Send failed: %s", log_prefix, e)
        if fallback is not None:
            try:
                return await fallback
            except Exception as e2:
                log.warning("%s Fallback failed: %s", log_prefix, e2)
    return None


async def safe_send_many(
    bot,
    user_ids: list[int],
    text: str,
    photo_id: Optional[str] = None,
    reply_markup=None,
    delay: float = 0.05,
    concurrent: int = 10,
) -> tuple[int, int]:
    """Массовая рассылка с семафором и retry.

    Returns:
        (sent_count, failed_count)
    """
    semaphore = asyncio.Semaphore(concurrent)
    sent = 0
    failed = 0

    async def _send_one(uid: int) -> None:
        nonlocal sent, failed
        async with semaphore:
            try:
                if photo_id:
                    await bot.send_photo(uid, photo=photo_id, caption=text, reply_markup=reply_markup)
                else:
                    await bot.send_message(uid, text, reply_markup=reply_markup)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                try:
                    if photo_id:
                        await bot.send_photo(uid, photo=photo_id, caption=text, reply_markup=reply_markup)
                    else:
                        await bot.send_message(uid, text, reply_markup=reply_markup)
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(delay)

    await asyncio.gather(*[_send_one(uid) for uid in user_ids], return_exceptions=True)
    return sent, failed
