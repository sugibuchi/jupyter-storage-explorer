"""A job's ``Progress`` as the explorer runs it (``JobProgress``): what
operations report (filesystems/operation.py), plus what the job and its
owner do with it: totals by item, cancelling, and reports to the page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.filesystems.operation import Progress

if TYPE_CHECKING:
    from collections.abc import Callable


class JobProgress(Progress):
    """The ``Progress`` the job runner gives a job's work, and so its
    operations.

    The job sets the totals (``add_total``, from the operations' ``measure``)
    and wraps each item in ``begin_item`` and ``end_item``, so that what an
    operation does not report (e.g. a folder moved by one rename) is counted
    when the item ends. ``on_change`` is called after each report, in the
    reporting thread (the runner sends progress to the page from it); the
    kernel's main thread reads ``snapshot()`` and calls ``cancel()``.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_change = on_change
        # Counts when the current item started, and its totals.
        self._item: tuple[int, int, int, int] | None = None

    def add_total(self, files: int = 0, bytes: int = 0) -> None:
        """Add files and bytes to the totals (from ``measure``, before the work)."""
        with self._lock:
            self.files_total += files
            self.bytes_total += bytes
        self._changed()

    def begin_item(self, files: int, bytes: int) -> None:
        """An item of ``files`` files and ``bytes`` bytes (as measured) starts."""
        with self._lock:
            self._item = (self.files_done, self.bytes_done, files, bytes)

    def end_item(self) -> None:
        """The current item is done: count what its method did not report."""
        with self._lock:
            if self._item is not None:
                files_at, bytes_at, files, size = self._item
                self.files_done = max(self.files_done, files_at + files)
                self.bytes_done = max(self.bytes_done, bytes_at + size)
                self._item = None
        self._changed()

    def cancel(self) -> None:
        """Ask the operation to stop (at its next ``check()``)."""
        self._cancel.set()

    def snapshot(self) -> dict[str, Any]:
        """The counts, consistent with one another, for the frontend."""
        with self._lock:
            return {
                "files_total": self.files_total,
                "bytes_total": self.bytes_total,
                "files_done": self.files_done,
                "bytes_done": self.bytes_done,
                "current": self.current,
            }

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()
