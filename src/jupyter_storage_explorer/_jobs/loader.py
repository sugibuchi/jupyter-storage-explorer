"""Loads: the slow reads behind what the explorer shows, e.g. a preview's
view, run in worker threads so the kernel stays free while they run.

Unlike jobs, loads run side by side and report nothing while they run: a
Spark session taking minutes to start must hold up neither copies nor other
previews. Each gives a ``Load``: once cancelled (e.g. another preview asked
for, or the panel closed), its result is closed instead of shown. A load's
work runs in a worker thread and must never touch traits or call ``send``;
what it gives is shown on the kernel's main thread. Without a running asyncio
loop (tests, scripts), loads run synchronously instead, as jobs do.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from jupyter_storage_explorer._jobs.runner import _Inline

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

T = TypeVar("T")

# How many loads run at once: a few previews and tabs opening side by side.
WORKERS = 4


class Load(Generic[T]):
    """A load submitted to a ``Loader``: ``cancel()`` it to have its result
    closed instead of shown. Cancelling a load that has ended does nothing."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class Loader:
    """Runs loads in worker threads, several at a time; each one's result is
    shown (``done``) or closed (``discard``) on the main thread."""

    def __init__(self, workers: int = WORKERS) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._main: Callable[[Callable[[], None]], Any] = loop.call_soon_threadsafe
            self._executor: concurrent.futures.Executor = (
                concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="jse-view"
                )
            )
        else:
            self._main = lambda fn: fn()
            self._executor = _Inline()

    def submit(
        self,
        work: Callable[[], T],
        done: Callable[[T], None],
        discard: Callable[[T], None],
    ) -> Load[T]:
        """Run ``work`` in a worker thread; then, on the main thread,
        ``done(result)``, or ``discard(result)`` if the load was cancelled
        meanwhile. ``work`` reports its own errors in its result: one it
        raises is only logged."""
        load: Load[T] = Load()

        def run() -> None:
            try:
                result = work()
            except Exception:
                log.exception("a load failed")
                return
            self._main(functools.partial(self._end, load, result, done, discard))

        self._executor.submit(run)
        return load

    @staticmethod
    def _end(
        load: Load[T],
        result: T,
        done: Callable[[T], None],
        discard: Callable[[T], None],
    ) -> None:
        try:
            (discard if load.cancelled else done)(result)
        except Exception:
            log.exception("ending a load failed")
