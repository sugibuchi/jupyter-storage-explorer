"""Loads: the slow reads behind what the explorer shows, e.g. a preview's
view or the data browser's rows, run in worker threads so the kernel stays
free while they run.

Unlike jobs, loads run side by side and report nothing while they run: a
Spark session taking minutes to start must hold up neither copies nor other
previews. Each gives a ``Load``: once cancelled (e.g. another preview asked
for, or the panel closed), its result is closed instead of shown. A load's
work runs in a worker thread and must never touch traits or call ``send``;
what it gives is shown on the kernel's main thread. Without a running asyncio
loop (tests, scripts), loads run synchronously instead, as jobs do.

Loads in the same lane run one at a time, in the order submitted: the data
browser's requests on one query, which is not safe to use from two threads at
once, and closing it after them.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import functools
import logging
import threading
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from jupyter_storage_explorer._jobs.runner import _Inline

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

log = logging.getLogger(__name__)

T = TypeVar("T")

# How many loads of the kernel's widgets run at once: a few previews, tabs
# and queries side by side.
WORKERS = 8

# The worker threads, shared by the kernel's loaders; created when first used.
_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _workers() -> concurrent.futures.ThreadPoolExecutor:
    global _executor  # noqa: PLW0603
    with _executor_lock:
        if _executor is None:
            _executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=WORKERS, thread_name_prefix="jse-load"
            )
        return _executor


class Load(Generic[T]):
    """A load submitted to a ``Loader``: ``cancel()`` it to have its result
    closed instead of shown. Cancelling a load that has ended does nothing.
    ``ended``: its result was shown or closed (or its work failed), which,
    without a loop, is before ``submit`` returns."""

    def __init__(self) -> None:
        self.cancelled = False
        self.ended = False

    def cancel(self) -> None:
        self.cancelled = True


class Loader:
    """Runs loads in worker threads, several at a time (one at a time in a
    lane); each one's result is shown (``done``) or closed (``discard``) on
    the main thread."""

    def __init__(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._main: Callable[[Callable[[], None]], Any] = loop.call_soon_threadsafe
            self._executor: concurrent.futures.Executor = _workers()
        else:
            self._main = lambda fn: fn()
            self._executor = _Inline()
        # The lanes running: lane -> the runs waiting in it.
        self._lanes: dict[Hashable, collections.deque[Callable[[], None]]] = {}
        self._lanes_lock = threading.Lock()

    def submit(
        self,
        work: Callable[[], T],
        done: Callable[[T], None],
        discard: Callable[[T], None],
        lane: Hashable | None = None,
    ) -> Load[T]:
        """Run ``work`` in a worker thread, after the loads of ``lane``
        submitted before; then, on the main thread, ``done(result)``, or
        ``discard(result)`` if the load was cancelled meanwhile. ``work``
        reports its own errors in its result: one it raises is only logged."""
        load: Load[T] = Load()

        def run() -> None:
            try:
                result = work()
            except Exception:
                log.exception("a load failed")
                self._main(functools.partial(setattr, load, "ended", True))
                return
            self._main(functools.partial(self._end, load, result, done, discard))

        # Without a loop, runs are in order already: one ends before the next.
        if lane is None or isinstance(self._executor, _Inline):
            self._executor.submit(run)
        else:
            self._run_in_lane(lane, run)
        return load

    def answer(
        self,
        lane: Hashable,
        work: Callable[[], dict[str, Any]],
        reply: Callable[[dict[str, Any]], None],
    ) -> None:
        """Answer a request in ``lane``: ``reply(work())`` on the main thread,
        or ``reply({"error"})`` if ``work`` raises."""

        def answered() -> dict[str, Any]:
            from jupyter_storage_explorer._explorer.common import (  # noqa: PLC0415
                error_text,
            )

            try:
                return work()
            except Exception as exc:
                log.exception("answering a request failed")
                return {"error": error_text(exc)}

        self.submit(answered, reply, reply, lane)

    def close_in_lane(self, lane: Hashable, close: Callable[[], object]) -> None:
        """Call ``close`` in ``lane``, after the loads submitted before: e.g.
        a query's, once no request reads it any more."""
        self.submit(close, _ignore, _ignore, lane)

    def _run_in_lane(self, lane: Hashable, run: Callable[[], None]) -> None:
        with self._lanes_lock:
            waiting = self._lanes.get(lane)
            if waiting is not None:
                waiting.append(run)
                return
            self._lanes[lane] = collections.deque()
        self._executor.submit(self._lane, lane, run)

    def _lane(self, lane: Hashable, run: Callable[[], None]) -> None:
        """In a worker thread: ``run``, then the runs that came meanwhile, in
        their order, until the lane is empty."""
        while True:
            try:
                run()
            except Exception:
                # E.g. the loop gone: the next runs still run.
                log.exception("a load failed")
            with self._lanes_lock:
                waiting = self._lanes[lane]
                if not waiting:
                    del self._lanes[lane]
                    return
                run = waiting.popleft()

    def _end(
        self,
        load: Load[T],
        result: T,
        done: Callable[[T], None],
        discard: Callable[[T], None],
    ) -> None:
        load.ended = True
        try:
            (discard if load.cancelled else done)(result)
        except Exception:
            if isinstance(self._executor, _Inline):
                raise  # to the caller, as without loads (e.g. on_change's functions)
            log.exception("ending a load failed")


def _ignore(_result: object) -> None:
    pass
