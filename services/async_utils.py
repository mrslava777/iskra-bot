"""Утилиты для асинхронных операций — общие хелперы."""
import asyncio
import logging

log = logging.getLogger("iskra.async_utils")


def fire(coro) -> None:
    """Fire-and-forget: запускает корутину или awaitable без ожидания результата.

    FIX: aiogram 3.x message.answer() возвращает Method object (SendMessage),
    который нужно await'ить. Принимаем любой Awaitable и оборачиваем в корутину.
    """
    if asyncio.iscoroutine(coro):
        task = asyncio.create_task(coro)
    else:
        # aiogram 3.x methods return objects that need to be awaited
        async def _wrapper():
            return await coro
        task = asyncio.create_task(_wrapper())
    task.add_done_callback(_handle_fire_exception)


def _handle_fire_exception(task: asyncio.Task) -> None:
    """Обработчик исключений для fire-and-forget задач."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.debug("fire-and-forget exception: %s", exc)
