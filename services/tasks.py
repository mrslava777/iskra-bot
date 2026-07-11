"""Утилита для fire-and-forget задач.

Раньше блок `create_task + add(set) + add_done_callback(discard)` копипастился
в start.py, browse.py, chat.py по многу раз. Вынесено в один хелпер, который
удерживает ссылку на задачу (иначе GC может её собрать до завершения) и
логирует необработанные исключения.

Использование:
    from services.tasks import spawn
    spawn(some_coro(...))
"""
import asyncio
import logging

log = logging.getLogger("iskra.tasks")

_background_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Запускает корутину как фоновую задачу с удержанием ссылки.

    Возвращает Task на случай, если вызывающему нужно её дождаться/отменить.
    Необработанные исключения логируются, а не теряются молча.
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.warning("Background task failed: %s", exc)

    task.add_done_callback(_done)
    return task
