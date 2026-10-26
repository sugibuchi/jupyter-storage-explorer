"""File operations, run in the background with progress reports and cancellation.

``StorageExplorer`` moves, copies, deletes and downloads files through a list
of ``FileSystemOperations`` objects (its ``operations`` argument): for each
operation it calls the first object's method, and the next object's if that
raises ``FileSystemOperations.NotSupported`` (the explorer's chain,
_jobs/operation_chain.py). Its
default list (``default_operations()`` in operations.py, with the predefined
operations) is ``AtomicMoveOperation``, for moves in one step
on local disks, then ``AsyncFsspecOperations``, for asynchronous filesystems
(s3fs, gcsfs, adlfs, ...), many files at a time, then ``FsspecOperations``,
which does everything with fsspec. So an object put before them can do some
operations its own way for some storage (e.g. server-side copies with the
storage's own client) and leave the rest to them.

Each method does its work synchronously (``StorageExplorer`` runs it in a
worker thread, see _jobs/runner.py) and reports to a ``Progress``: bytes and files
done, the file being worked on, and through ``Progress.check`` whether the
user cancelled, which raises ``OperationCancelled``.
"""

from __future__ import annotations

import dataclasses
import threading
from typing import TYPE_CHECKING, Any

from fsspec.callbacks import Callback

from jupyter_storage_explorer import _infos
from jupyter_storage_explorer.filesystems import _streaming

if TYPE_CHECKING:
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
    reads and cancels. The explorer gives operations a subclass of its own
    (its job runner's), which also keeps the totals, reports to the page and
    cancels; a plain ``Progress()`` serves to call operations outside an
    explorer, e.g. in their tests.

    Attributes
    ----------
    files_total, bytes_total : int
        Files and bytes the job works on, as measured.
    files_done, bytes_done : int
        Files and bytes done so far.
    current : str
        The name of the file being worked on.
    cancelled : bool
        Whether the user has cancelled.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.files_total = 0
        self.bytes_total = 0
        self.files_done = 0
        self.bytes_done = 0
        self.current = ""  # the name of the file being worked on

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

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _changed(self) -> None:
        """After each report: nothing here; the job runner's subclass reports
        to the page."""


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


@dataclasses.dataclass
class Measurement:
    """What ``FileSystemOperations.measure`` found at a path.

    Attributes
    ----------
    files : int
        Files: 1 for a file; for a folder, those in it and its subfolders.
    bytes : int
        Their total size.
    folders : int
        Folders in a folder and its subfolders (not the folder itself).
    oldest, newest : tuple of (float, str), optional
        The modification time (seconds since the epoch) and path of the
        oldest and newest files; None when no file has a modification time.
    errors : list of str
        Folders that could not be listed ("path: reason"), left out.
    complete : bool
        False if measuring stopped before the end (the user cancelled): the
        counts are of what was found until then.
    """

    files: int = 0
    bytes: int = 0
    folders: int = 0
    oldest: tuple[float, str] | None = None
    newest: tuple[float, str] | None = None
    errors: list[str] = dataclasses.field(default_factory=list)
    complete: bool = True

    def merge(self, other: Measurement) -> None:
        """Add what ``other`` found, e.g. a file of a folder, or another item
        selected.

        Parameters
        ----------
        other : Measurement
            Another path's measurement.
        """
        self.files += other.files
        self.bytes += other.bytes
        self.folders += other.folders
        if other.oldest is not None and (
            self.oldest is None or other.oldest[0] < self.oldest[0]
        ):
            self.oldest = other.oldest
        if other.newest is not None and (
            self.newest is None or other.newest[0] > self.newest[0]
        ):
            self.newest = other.newest
        self.errors += other.errors
        self.complete = self.complete and other.complete


def measure_file_info(info: dict[str, Any]) -> Measurement:
    """A file's measurement, from its fsspec info dict.

    Parameters
    ----------
    info : dict
        The file's info dict (e.g. from ``info`` or ``ls(detail=True)``), with
        "name", and "size" and a modification time when the filesystem gives
        them.

    Returns
    -------
    Measurement
        One file of its size, which is the oldest and newest file if it has
        a modification time.
    """
    ts = _infos.mtime(info)
    found = None if ts is None else (ts, info["name"].rstrip("/"))
    return Measurement(files=1, bytes=info.get("size") or 0, oldest=found, newest=found)


class FileSystemOperations:
    """File operations for ``StorageExplorer``, to do some of them in a way of
    your own (see the module docstring).

    Every method raises ``NotSupported``. Override those you implement, and
    raise ``self.NotSupported`` in them too for filesystems (or cases) you do
    not handle: each method is given the filesystem, and the next operations
    object (in the end ``FsspecOperations``, see ``filesystems.operations``)
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
    one: e.g. a file pasted from another storage. The caller tells which
    with ``same``: the explorer, as its filesystem mappers decide.

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

    def measure(
        self, fs: AbstractFileSystem, path: str, progress: Progress | None = None
    ) -> Measurement:
        """Count the files and folders at a path, their size, and the oldest
        and newest files.

        Used two ways. Without ``progress``: for the progress bar of a job,
        for each of its items before it starts, so it should be quick
        compared with the operation itself (e.g. one recursive listing).
        With ``progress``: for "Properties" in the explorer, where measuring
        is the job itself, so it reports as it goes and can be cancelled
        (e.g. listing folder by folder).

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem ``path`` is on.
        path : str
            A file or folder on ``fs`` (an fsspec path of ``fs``).
        progress : Progress, optional
            Where to report the files found (``advance``, their bytes too)
            and the folder being listed (``working_on``), and check for a
            cancel (``progress.check()``, between listings). Folders that
            cannot be listed are then left out, in ``Measurement.errors``,
            rather than raising; and once the user cancels, measuring stops
            and returns what it found, with ``complete`` False.

        Returns
        -------
        Measurement
            What was found.

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
        *,
        same: bool,
    ) -> None:
        """Move a file or folder (with everything in it), within a filesystem
        or to another one.

        Between filesystems (``same`` False), a move is a copy then a
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

        same : bool
            Whether ``source_fs`` and ``target_fs`` are one filesystem, as
            the explorer's filesystem mappers tell (outside an explorer, e.g.
            ``filesystems.same_filesystem``), so that a path of one is the
            same file on the other.

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
        *,
        same: bool,
    ) -> None:
        """Copy a file or folder (with everything in it), within a filesystem
        or to another one.

        Between filesystems (``same`` False), a file that fails or is
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

        same : bool
            Whether ``source_fs`` and ``target_fs`` are one filesystem, as
            the explorer's filesystem mappers tell (outside an explorer, e.g.
            ``filesystems.same_filesystem``), so that a path of one is the
            same file on the other.

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

        Through the kernel, without a local temporary file. A file up to 8
        MiB is read whole, then written in one call. A larger one streams:
        its next blocks are read while the last is written. A failed or
        cancelled copy leaves no partial file at ``target``, though a file
        it was replacing on a local disk is spoiled. Override it to copy
        files between two storages another way, e.g. server-side between two
        accounts of one cloud.

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
        _streaming.copy_file(source_fs, path, target_fs, target, progress)

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
