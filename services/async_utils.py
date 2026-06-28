"""Утилиты для асинхронных операций — общие хелперы."""
import asyncio
import logging

log = logging.getLogger("iskra.async_utils")


def fire(coro) -> None:
    """Fire-and-forget: запускает корутину без ожидания результата.

    Ошибки логируются, но не пробрасываются.
    Используется для неблокирующих побочных операций (уведомления, значки, статистика).
    """
    task = asyncio.create_task(coro)
    task.add_done_callback(_handle_fire_exception)


def _handle_fire_exception(task: asyncio.Task) -> None:
    """Обработчик исключений для fire-and-forget задач."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.debug("fire-and-forget exception: %s", exc)
