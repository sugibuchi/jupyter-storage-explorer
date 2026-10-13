"""File operations, run in the background with progress reports and cancellation.

``StorageExplorer`` moves, copies, deletes and downloads files through a list
of ``FileSystemOperations`` objects (its ``operations`` argument): for each
operation it calls the first object's method, and the next object's if that
raises ``FileSystemOperations.NotSupported`` (see ``OperationChain``). Its
default list (``StorageExplorer.default_operations``, from the
``filesystems`` package) is ``AtomicMoveOperation``, for moves in one step
on local disks, then ``AsyncFsspecOperations``, for asynchronous filesystems
(s3fs, gcsfs, adlfs, ...), many files at a time, then ``FsspecOperations``,
which does everything with fsspec. So an object put before them can do some
operations its own way for some storage (e.g. server-side copies with the
storage's own client) and leave the rest to them.

Each method does its work synchronously (``StorageExplorer`` runs it in a
worker thread, see jobs.py) and reports to a ``Progress``: bytes and files
done, the file being worked on, and through ``Progress.check`` whether the
user cancelled, which raises ``OperationCancelled``.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from typing import TYPE_CHECKING, Any

from fsspec.callbacks import Callback

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fsspec import AbstractFileSystem


class OperationCancelled(Exception):
    """Raised by ``Progress.check`` once the user has cancelled the operation."""


class Progress:
    """How far an operation (a job) has got, and whether the user cancelled it.

    ``FileSystemOperations`` methods report to it: files and bytes done
    (``advance``, or a ``callback()`` given to fsspec transfers), the file
    being worked on (``working_on``), and they call ``check()`` between steps
    so that a cancel takes effect soon. Reporting is optional: totals come
    from ``FileSystemOperations.measure`` for each item (file or folder) of
    the job, and when an item ends, what its method did not report is counted
    as done, so a folder moved by a single rename still counts all its files.

    Thread-safe: the job's worker thread reports; the kernel's main thread
    reads (``snapshot``) and cancels.

    Parameters
    ----------
    on_change : callable, optional
        Called with no arguments after each report, in the reporting thread
        (the job runner sends progress to the frontend from it).

    Attributes
    ----------
    files_total, bytes_total : int
        Files and bytes the job works on, as measured.
    files_done, bytes_done : int
        Files and bytes done so far.
    current : str
        The name of the file being worked on.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._on_change = on_change
        self.files_total = 0
        self.bytes_total = 0
        self.files_done = 0
        self.bytes_done = 0
        self.current = ""  # the name of the file being worked on
        # Counts when the current item started, and its totals.
        self._item: tuple[int, int, int, int] | None = None

    # --- Reported by FileSystemOperations methods ---

    def advance(self, files: int = 0, bytes: int = 0) -> None:
        """Report work done since the last report.

        Parameters
        ----------
        files : int, default 0
            Files done (e.g. 1 after copying a file of a folder).
        bytes : int, default 0
            Bytes done. Do not report bytes a ``callback()`` reports already.
        """
        with self._lock:
            self.files_done += files
            self.bytes_done += bytes
        self._changed()

    def working_on(self, name: str) -> None:
        """Report the file now being worked on, shown to the user.

        Parameters
        ----------
        name : str
            Its name, e.g. "part-03.csv" (not a whole path).
        """
        with self._lock:
            self.current = name
        self._changed()

    def check(self) -> None:
        """Stop if the user has cancelled. Call it between steps, e.g. files.

        Raises
        ------
        OperationCancelled
            Once the user has cancelled the job. Let it propagate: the job
            then reports what was done before.
        """
        if self._cancel.is_set():
            raise OperationCancelled

    def callback(self, count: bool = True) -> Callback:
        """An fsspec callback for a transfer, e.g. ``fs.get_file(..., callback=...)``.

        Parameters
        ----------
        count : bool, default True
            Whether it reports the transfer's bytes; false e.g. for the
            second half of a copy through a temporary file, whose bytes the
            first half reported.

        Returns
        -------
        fsspec.callbacks.Callback
            Reports bytes as the transfer goes, and stops it (raising
            ``OperationCancelled``) once the user has cancelled.
        """
        return _ProgressCallback(self, count)

    # --- Reported by the job ---

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

    # --- Used by the job's owner ---

    def cancel(self) -> None:
        """Ask the operation to stop (at its next ``check()``)."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        """Whether the user has cancelled."""
        return self._cancel.is_set()

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


class _ProgressCallback(Callback):
    """Reports a transfer's bytes to a ``Progress``, and stops it once cancelled."""

    def __init__(self, progress: Progress, count: bool) -> None:
        super().__init__()
        self._progress = progress
        self._count = count
        self._reported = 0

    def call(self, *args: Any, **kwargs: Any) -> None:
        # Called by fsspec after each update of ``value`` (bytes so far).
        if self._count and self.value > self._reported:
            self._progress.advance(bytes=self.value - self._reported)
            self._reported = self.value
        self._progress.check()


class FileSystemOperations:
    """File operations for ``StorageExplorer``, to do some of them in a way of
    your own (see the module docstring).

    Every method raises ``NotSupported``. Override those you implement, and
    raise ``self.NotSupported`` in them too for filesystems (or cases) you do
    not handle: each method is given the filesystem, and the next operations
    object (in the end ``FsspecOperations``, see the ``filesystems`` package)
    then does it. Any other exception
    is an error of the operation, reported to the user, including
    ``NotImplementedError`` raised by a library.

    One object serves every explorer it is given to and runs in their jobs'
    threads, so it may hold state, e.g. a client for the storage, as long as
    it is thread-safe.

    Paths are not URLs: they are fsspec paths of the filesystem passed with
    them, as that filesystem lists them (without its protocol), e.g.

    ======================  ===========================================
    Filesystem              Path
    ======================  ===========================================
    ``LocalFileSystem``     ``"/home/me/raw/sales.csv"``
    ``S3FileSystem``        ``"my-bucket/raw/sales.csv"``
    ``AzureBlobFileSystem`` ``"container/raw/sales.csv"`` (the account
                            is the filesystem's ``account_name``)
    ``MemoryFileSystem``    ``"/raw/sales.csv"``
    ======================  ===========================================

    ``fs.unstrip_protocol(path)`` gives a path's URL, if an implementation
    needs one. Local paths (``local_path``) are paths on the kernel's machine.

    ``move`` and ``copy`` are given two filesystems, which may be the same
    one (``same_filesystem`` tells): e.g. a file pasted from another storage.

    Targets do not exist (an existing file is deleted first when
    overwriting), and their parent folders do.
    """

    class NotSupported(Exception):
        """Raised by a method for an operation this object does not do (e.g.
        on another filesystem), for the next operations object to do it.

        Its own exception, so that a ``NotImplementedError`` raised for other
        reasons (e.g. by a filesystem lacking a method) is reported as an
        error, not taken to mean "not supported".
        """

    def measure(self, fs: AbstractFileSystem, path: str) -> tuple[int, int]:
        """Count the files at a path and their size, for the progress bar.

        Called for each item of a job before it starts; it should be quick
        compared with the operation itself (e.g. one listing).

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            A file or folder on ``fs`` (an fsspec path of ``fs``).

        Returns
        -------
        tuple of (int, int)
            The number of files (1 for a file; for a folder, those in it and
            its subfolders) and their total size in bytes.

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        """
        raise self.NotSupported

    def move(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """Move a file or folder (with everything in it), within a filesystem
        or to another one.

        Between filesystems (see ``same_filesystem``), a move is a copy then a
        delete: a file that fails or is cancelled must not be left partly
        written at ``target``, nor deleted from ``source`` before its copy is
        complete.

        Parameters
        ----------
        source_fs : AbstractFileSystem
            The filesystem ``source`` is on.
        source : str
            The file or folder to move (an fsspec path of ``source_fs``).
        target_fs : AbstractFileSystem
            The filesystem ``target`` is on: ``source_fs``, or another one.
        target : str
            The path it gets (an fsspec path of ``target_fs``), which does not
            exist; its parent folder does.
        progress : Progress
            Where to report files and bytes moved (optional within a
            filesystem, where a move is often a rename) and check for a
            cancel (``progress.check()``, between steps).

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle these filesystems.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def copy(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """Copy a file or folder (with everything in it), within a filesystem
        or to another one.

        Between filesystems (see ``same_filesystem``), a file that fails or is
        cancelled must not be left partly written at ``target`` (e.g. copy
        through a temporary file).

        Parameters
        ----------
        source_fs : AbstractFileSystem
            The filesystem ``source`` is on: ``target_fs``, another storage
            of the explorer, or one read from a URL with the environment's
            credentials.
        source : str
            The file or folder to copy (an fsspec path of ``source_fs``).
        target_fs : AbstractFileSystem
            The filesystem ``target`` is on.
        target : str
            The path of the copy (an fsspec path of ``target_fs``), which
            does not exist, except a file being overwritten; its parent folder
            does.
        progress : Progress
            Where to report files and bytes copied (``advance``, or
            ``callback()`` for transfers) and check for a cancel
            (``progress.check()``, e.g. between files).

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle these filesystems.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        """Delete a file or folder (with everything in it).

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            The file or folder to delete (an fsspec path of ``fs``).
        progress : Progress
            Where to report files deleted (``advance``) and check for a
            cancel (``progress.check()``, e.g. between batches of files).

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        """Copy a file of a filesystem to the kernel's machine.

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            The file to copy (an fsspec path of ``fs``; never a folder).
        local_path : str
            Where to write it on the kernel's machine: a temporary file, moved
            into place by the caller once complete.
        progress : Progress
            Where to report bytes copied (e.g. ``callback()``, given to
            fsspec's ``get_file``) and check for a cancel.

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        """Copy a file of the kernel's machine to a filesystem.

        Parameters
        ----------
        local_path : str
            The file to copy, on the kernel's machine.
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            Where to write it (an fsspec path of ``fs``); its parent folder
            exists.
        progress : Progress
            Where to report bytes copied (e.g. ``callback()``, given to
            fsspec's ``put_file``) and check for a cancel.

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        """Create a new, empty folder ("Create a folder" in the explorer).

        Quick, so not run as a job: no progress. On object stores, where
        empty folders do not exist, an implementation may e.g. put a
        placeholder file in it.

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            The folder to create (an fsspec path of ``fs``), which does not
            exist; its parent folder does.

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        """
        raise self.NotSupported

    # --- Helpers for implementations: one file between two filesystems ---

    def _copy_file(
        self,
        source_fs: AbstractFileSystem,
        path: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """Copy one file to another filesystem, for ``copy`` and ``_move_file``.

        Through a local temporary file: read whole, then written, so a
        failed (or cancelled) copy never leaves a partial file at ``target``.
        Override it to copy files between two storages another way, e.g.
        server-side between two accounts of one cloud.

        Parameters
        ----------
        source_fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            The file to copy (an fsspec path of ``source_fs``; never a folder).
        target_fs : AbstractFileSystem
            Another filesystem, ``target`` is on.
        target : str
            The path of the copy (an fsspec path of ``target_fs``); its
            parent folder exists.
        progress : Progress
            Where to report bytes copied (e.g. ``callback()``) and check for
            a cancel; the caller counts the file once copied.

        Raises
        ------
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        handle, temp_path = tempfile.mkstemp(prefix="jse-copy-")
        os.close(handle)
        try:
            source_fs.get_file(path, temp_path, callback=progress.callback())
            progress.check()
            target_fs.put_file(
                temp_path, target, callback=progress.callback(count=False)
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_path)

    def _move_file(
        self,
        source_fs: AbstractFileSystem,
        path: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """Move one file to another filesystem: ``_copy_file``, then the source
        deleted once the copy is complete.

        Parameters
        ----------
        source_fs, path, target_fs, target, progress
            As for ``_copy_file``.

        Raises
        ------
        OSError
            If the file was copied but its source could not be deleted: it
            is then in both places, which the user should know.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        self._copy_file(source_fs, path, target_fs, target, progress)
        try:
            source_fs.rm_file(path)
        except Exception as exc:
            raise self._not_removed(path, exc) from exc

    @staticmethod
    def _not_removed(path: str, exc: Exception) -> OSError:
        """The error of a file moved by a copy whose source was left."""
        name = path.rstrip("/").rsplit("/", 1)[-1]
        return OSError(f"{name} was copied, but not deleted from its source: {exc}")


class OperationChain:
    """Calls an operation on the first of ``operations`` that supports it
    (see the module docstring), in the order given: which objects there are,
    defaults included, is up to the caller (e.g.
    ``StorageExplorer.default_operations``)."""

    def __init__(self, operations: Sequence[FileSystemOperations]) -> None:
        if not operations:
            raise ValueError("no operations objects given")
        self.operations = list(operations)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_") or not hasattr(FileSystemOperations, name):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            for operations in self.operations:
                try:
                    return getattr(operations, name)(*args, **kwargs)
                except FileSystemOperations.NotSupported:
                    continue
            raise FileSystemOperations.NotSupported(
                f"no operations object does {name} on this filesystem"
            )

        return call


def same_filesystem(a: AbstractFileSystem, b: AbstractFileSystem) -> bool:
    """Whether two filesystem objects reach the same storage.

    fsspec caches its filesystems by class and arguments, and compares them by
    those (``fs1 == fs2``), so two objects made with the same arguments count
    as one, e.g. an explorer's storage and the one a URL opens.

    Parameters
    ----------
    a, b : AbstractFileSystem
        The filesystems to compare.

    Returns
    -------
    bool
        True if a path of one is the same file on the other.
    """
    return a is b or a == b
