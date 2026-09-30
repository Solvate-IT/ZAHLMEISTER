"""Run CPU- or subprocess-heavy request work off the event loop.

An ``async def`` endpoint that parses a scanned PDF (pdftoppm + tesseract), builds
a PDF/XLSX export or zips an account export would otherwise block its process's
event loop — and with it every other request of that process, payment webhooks
and health checks included. ``run_blocking`` moves the work into a thread and
bounds how many such tasks run at once per process
(``settings.blocking_task_concurrency``), so a burst of imports queues instead of
exhausting CPU and memory.
"""
import asyncio
import functools
import weakref
from collections.abc import Callable

from app.core.config import settings

# One semaphore per event loop: asyncio primitives must not cross loops (tests run
# several), and a process only ever has one loop in production.
_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, settings.blocking_task_concurrency))
        _semaphores[loop] = semaphore
    return semaphore


async def run_blocking[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    async with _semaphore():
        return await asyncio.to_thread(functools.partial(function, *args, **kwargs))
