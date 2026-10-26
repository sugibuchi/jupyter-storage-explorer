"""Jobs: long file operations run in a worker thread, so the kernel stays free.

A job's work (a function given a ``JobProgress``) runs in the ``JobRunner``'s
thread; everything else about it runs on the kernel's main thread, where
widget state may change: reporting its progress (``notify``) and finishing
it (e.g. refreshing the file list). In a kernel, the main thread runs an
asyncio loop, which worker threads hand functions to; without one (tests,
scripts), jobs run synchronously instead.

Functions handed to the loop run in the context variables of the request
that submitted the job, copied when it was submitted. The kernel keeps the
request being answered there, which ``send`` needs: ipykernel 7.0, for one,
fails to send in a worker thread's own, empty context.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._jobs.progress import JobProgress
from jupyter_storage_explorer.filesystems.operation import OperationCancelled

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

# How often a running job's progress is sent, at most (seconds).
REPORT_INTERVAL = 0.2


@dataclass(eq=False)
class Job:
    """One operation: "queued", then "running", then "done", "failed" or
    "cancelled". ``result`` is what its work returned (e.g. {"moved": [...],
    "errors": [...]}); ``error`` why it failed."""

    id: str
    kind: str
    title: str
    progress: JobProgress = field(default_factory=JobProgress)
    state: str = "queued"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def finished(self) -> bool:
        return self.state in ("done", "failed", "cancelled")

    def snapshot(self) -> dict[str, Any]:
        """The job as the frontend shows it."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "cancelling": self.progress.cancelled and not self.finished,
            **self.progress.snapshot(),
            "result": self.result if self.finished else None,
            "error": self.error,
        }


class _Inline(concurrent.futures.Executor):
    """Runs work at once, in the calling thread (no kernel loop to report to)."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        future.set_result(fn(*args, **kwargs))
        return future


def main_thread(
    loop: asyncio.AbstractEventLoop | None,
) -> Callable[[Callable[[], None], contextvars.Context], Any]:
    """How worker threads run a function on the main thread, in the context
    given: handed to ``loop``, or, without one, at once."""
    if loop is None:
        return lambda fn, context: fn()
    return lambda fn, context: loop.call_soon_threadsafe(fn, context=context)


class JobRunner:
    """Runs jobs one at a time, in submission order.

    ``notify(job)`` is called on the main thread whenever a job changes: at
    most every ``REPORT_INTERVAL`` seconds while it runs, and when it starts
    and ends. Job ids are ``prefix`` and a number, so that the jobs of
    several runners notifying the same frontend have different ids.
    """

    def __init__(self, notify: Callable[[Job], None], prefix: str = "job") -> None:
        self._notify = notify
        self._prefix = prefix
        self.jobs: dict[str, Job] = {}
        self._ids = itertools.count(1)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._main = main_thread(loop)
        if loop is not None:
            self._executor: concurrent.futures.Executor = (
                concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="jse-job"
                )
            )
        else:
            self._executor = _Inline()

    def submit(
        self,
        kind: str,
        title: str,
        work: Callable[[JobProgress], dict[str, Any]],
        finish: Callable[[Job], None] | None = None,
        update: Callable[[Job], None] | None = None,
    ) -> Job:
        """Queue ``work``; once it has ended (whatever the outcome), ``finish(job)``
        runs on the main thread, before the final ``notify``. While it runs,
        ``update(job)`` runs on the main thread before each progress report
        (e.g. to show what it has changed so far)."""
        job = Job(id=f"{self._prefix}-{next(self._ids)}", kind=kind, title=title)
        context = contextvars.copy_context()
        last = [0.0]
        lock = threading.Lock()

        def report() -> None:
            # From the job's thread: send at most every REPORT_INTERVAL seconds.
            now = time.monotonic()
            with lock:
                if now - last[0] < REPORT_INTERVAL:
                    return
                last[0] = now
            self._main(lambda: self._report(job, update), context)

        job.progress = JobProgress(on_change=report)
        self.jobs[job.id] = job
        log.debug("Job %s queued: %s", job.id, job.title)
        self._notify(job)
        self._executor.submit(self._run, job, work, finish, context)
        return job

    def cancel(self, job_id: str) -> bool:
        """Ask job ``job_id`` to stop; False if there is no such job (e.g. it has ended)."""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        log.info("Job %s cancelled by the user", job.id)
        job.progress.cancel()
        self._notify(job)
        return True

    def _report(self, job: Job, update: Callable[[Job], None] | None) -> None:
        """On the main thread: a running job's progress, after ``update``."""
        if job.finished:
            return  # a late report: ``finish`` has shown everything
        if update is not None:
            try:
                update(job)
            except Exception:
                log.exception("updating for job %s (%s) failed", job.id, job.title)
        self._notify_unless_finished(job)

    def _notify_unless_finished(self, job: Job) -> None:
        # A late progress report must not overwrite the final state.
        if not job.finished:
            self._notify(job)

    def _run(
        self,
        job: Job,
        work: Callable[[JobProgress], dict[str, Any]],
        finish: Callable[[Job], None] | None,
        context: contextvars.Context,
    ) -> None:
        """In the job's thread: do the work, then finish on the main thread."""
        started = time.monotonic()
        if job.progress.cancelled:
            job.state = "cancelled"  # cancelled while queued
        else:
            job.state = "running"
            log.info("Job %s started: %s", job.id, job.title)
            self._main(lambda: self._notify_unless_finished(job), context)
            try:
                job.result = work(job.progress) or {}
                job.state = "cancelled" if job.result.get("cancelled") else "done"
            except OperationCancelled:
                job.state = "cancelled"
            except Exception as exc:
                log.exception("job %s (%s) failed", job.id, job.title)
                job.state = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
        _log_end(job, time.monotonic() - started)
        self._main(lambda: self._end(job, finish), context)

    def _end(self, job: Job, finish: Callable[[Job], None] | None) -> None:
        if finish is not None:
            try:
                finish(job)
            except Exception:
                log.exception("finishing job %s (%s) failed", job.id, job.title)
        self.jobs.pop(job.id, None)
        self._notify(job)


def _log_end(job: Job, seconds: float) -> None:
    """Log how ``job`` ended: its counts of items by outcome (its result's
    lists, e.g. "moved"), the bytes and the time. The items' errors, which the
    user sees in the job's report, are a warning, with the first of them."""
    progress = job.progress.snapshot()
    counts = [
        f"{len(names)} {key}"
        for key, names in job.result.items()
        if isinstance(names, list) and names and key != "errors"
    ]
    counts.append(f"{progress['files_done']} files, {progress['bytes_done']} bytes")
    log.info("Job %s %s in %.1f s: %s", job.id, job.state, seconds, ", ".join(counts))
    errors = job.result.get("errors") or []
    if errors:
        log.warning(
            "Job %s (%s): %d errors, the first: %s",
            job.id,
            job.title,
            len(errors),
            errors[0],
        )
