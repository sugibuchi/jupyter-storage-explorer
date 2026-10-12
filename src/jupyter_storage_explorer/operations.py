"""File operations, run in the background with progress reports and cancellation.

``StorageExplorer`` moves, copies, deletes and downloads files through a list
of ``FileSystemOperations`` objects (its ``operations`` argument): for each
operation it calls the first object's method, and the next object's if that
raises ``FileSystemOperations.NotSupported``, ending with the defaults:
``AsyncFsspecOperations`` for asynchronous filesystems (s3fs, gcsfs, adlfs,
...), many files at a time, then ``FsspecOperations``, which does everything
with fsspec. So an object can do some operations its own way for some
storage (e.g. server-side copies with the storage's own client) and leave
the rest to the next ones.

Each method does its work synchronously (``StorageExplorer`` runs it in a
worker thread, see jobs.py) and reports to a ``Progress``: bytes and files
done, the file being worked on, and through ``Progress.check`` whether the
user cancelled, which raises ``OperationCancelled``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import threading
from typing import TYPE_CHECKING, Any

from fsspec.asyn import AsyncFileSystem, sync
from fsspec.callbacks import Callback

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from fsspec import AbstractFileSystem


class OperationCancelled(Exception):
    """Raised by ``Progress.check`` once the user has cancelled the operation."""


class Progress:
    """How far an operation (a job) has got, reported by the methods doing it.

    Totals come first, from ``FileSystemOperations.measure`` for each item
    (file or folder) the job works on; then the methods report files and
    bytes done with ``advance`` (or a ``callback`` given to fsspec). Methods
    need not report everything: when an item is finished (``end_item``), what
    it did not report is counted as done, so a folder moved by a single rename
    still counts all its files.

    Thread-safe: the job's thread reports, the kernel's main thread reads
    (``snapshot``) and cancels. ``on_change`` is called (in the job's thread)
    after each report.
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

    # --- Reported by the job ---

    def add_total(self, files: int = 0, bytes: int = 0) -> None:
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

    # --- Reported by FileSystemOperations methods ---

    def advance(self, files: int = 0, bytes: int = 0) -> None:
        """``files`` more files and ``bytes`` more bytes done."""
        with self._lock:
            self.files_done += files
            self.bytes_done += bytes
        self._changed()

    def working_on(self, name: str) -> None:
        """The file now being worked on, shown to the user."""
        with self._lock:
            self.current = name
        self._changed()

    def check(self) -> None:
        """Raise ``OperationCancelled`` if the user has cancelled. Call it
        between steps, e.g. files, so a cancel takes effect soon."""
        if self._cancel.is_set():
            raise OperationCancelled

    def callback(self, count: bool = True) -> Callback:
        """An fsspec callback for a transfer (``get_file``, ``put_file``, ...):
        reports its bytes (unless ``count`` is false, e.g. for the second half
        of a copy through a temporary file) and stops it once cancelled."""
        return _ProgressCallback(self, count)

    # --- Used by the job's owner ---

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
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
    object (in the end ``FsspecOperations``) then does it. Any other exception
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
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        """Move a file or folder (with everything in it) within a filesystem.

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem both paths are on.
        source : str
            The file or folder to move (an fsspec path of ``fs``).
        target : str
            The path it gets (an fsspec path of ``fs``), which does not exist;
            its parent folder does.
        progress : Progress
            Where to report progress (optional) and check for a cancel
            (``progress.check()``, between steps).

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def copy(
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        """Copy a file or folder (with everything in it) within a filesystem.

        Parameters
        ----------
        fs : AbstractFileSystem
            The filesystem both paths are on.
        source : str
            The file or folder to copy (an fsspec path of ``fs``).
        target : str
            The path of the copy (an fsspec path of ``fs``), which does not
            exist, except a file being overwritten; its parent folder does.
        progress : Progress
            Where to report files and bytes copied (``advance``, or
            ``callback()`` for transfers) and check for a cancel
            (``progress.check()``, e.g. between files).

        Raises
        ------
        FileSystemOperations.NotSupported
            If this object does not handle ``fs``.
        OperationCancelled
            From ``progress.check()``, once the user has cancelled.
        """
        raise self.NotSupported

    def copy_between(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """Copy a file or folder (with everything in it) from another filesystem.

        A file that fails or is cancelled must not be left partly written at
        ``target`` (e.g. copy through a temporary file).

        Parameters
        ----------
        source_fs : AbstractFileSystem
            The filesystem ``source`` is on (e.g. another storage, read with
            the environment's credentials).
        source : str
            The file or folder to copy (an fsspec path of ``source_fs``).
        fs : AbstractFileSystem
            The filesystem ``target`` is on: the one the explorer shows.
        target : str
            The path of the copy (an fsspec path of ``fs``), which does not
            exist, except a file being overwritten; its parent folder does.
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


class FsspecOperations(FileSystemOperations):
    """Every operation, with fsspec's API: works on any filesystem.

    Folders are copied and deleted file by file (deletions in batches), so
    progress shows and a cancel takes effect between files. Copies between
    filesystems go through local temporary files.
    """

    # Files deleted per request when deleting a folder: object stores delete
    # many files in one request, and cancelling takes effect between batches.
    DELETE_BATCH = 100

    def measure(self, fs: AbstractFileSystem, path: str) -> tuple[int, int]:
        if not fs.isdir(path):
            return 1, fs.info(path).get("size") or 0
        files = fs.find(path, detail=True)
        return len(files), sum(i.get("size") or 0 for i in files.values())

    def move(
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        progress.working_on(_name(source))
        if fs.isdir(source):
            fs.mv(source, target, recursive=True)
        else:
            fs.mv(source, target)

    def copy(
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        if not fs.isdir(source):
            progress.working_on(_name(source))
            fs.cp_file(source, target)
            return
        for path, dest, size in _tree(fs, source, target, fs):
            progress.check()
            progress.working_on(_name(path))
            fs.cp_file(path, dest)
            progress.advance(files=1, bytes=size)

    def copy_between(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        if not source_fs.isdir(source):
            progress.working_on(_name(source))
            _copy_through_temp(source_fs, source, fs, target, progress)
            return
        for path, dest, _size in _tree(source_fs, source, target, fs):
            progress.check()
            progress.working_on(_name(path))
            _copy_through_temp(source_fs, path, fs, dest, progress)
            progress.advance(files=1)

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        if not fs.isdir(path):
            progress.working_on(_name(path))
            fs.rm_file(path)
            return
        files = fs.find(path, detail=True)
        names = list(files)
        for start in range(0, len(names), self.DELETE_BATCH):
            progress.check()
            batch = names[start : start + self.DELETE_BATCH]
            progress.working_on(_name(batch[-1]))
            fs.rm(batch)
            progress.advance(
                files=len(batch), bytes=sum(files[n].get("size") or 0 for n in batch)
            )
        # The folders left, e.g. on local disks.
        if fs.exists(path):
            fs.rm(path, recursive=True)

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        progress.working_on(_name(path))
        fs.get_file(path, local_path, callback=progress.callback())

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        progress.working_on(_name(path))
        fs.put_file(local_path, path, callback=progress.callback())

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        fs.makedirs(path, exist_ok=False)


class AsyncFsspecOperations(FileSystemOperations):
    """Every operation on asynchronous fsspec filesystems (s3fs, gcsfs, adlfs,
    HTTP, ...), many files at a time: their coroutine methods (``_cp_file``,
    ``_rm``, ``_get_file``, ...) run on the filesystem's event loop with
    ``fsspec.asyn.sync``, in batches of ``concurrency`` files. Object stores
    take about as long for a small file as for none, so copying and deleting
    folders of many files is much faster than one file at a time.

    Other filesystems (and async ones made for use within a running event
    loop, ``asynchronous=True``) raise ``FileSystemOperations.NotSupported``, for
    ``FsspecOperations`` to do them. So do folder moves: some storages rename
    a folder in one step (e.g. Azure Data Lake Gen2), which the filesystem's
    own ``mv`` does.

    A cancel takes effect between batches, and within a batch for files not
    yet started and transfers under way.

    Parameters
    ----------
    concurrency : int
        Files copied (or downloaded) at a time.
    delete_batch : int
        Files deleted per ``_rm`` call: object stores delete many in one
        request (S3: up to 1,000).
    """

    def __init__(self, concurrency: int = 32, delete_batch: int = 1000) -> None:
        self.concurrency = concurrency
        self.delete_batch = delete_batch

    def measure(self, fs: AbstractFileSystem, path: str) -> tuple[int, int]:
        loop = _loop_of(fs)
        info = sync(loop, fs._info, path)
        if info.get("type") != "directory":
            return 1, info.get("size") or 0
        files = sync(loop, fs._find, path, detail=True)
        return len(files), sum(i.get("size") or 0 for i in files.values())

    def move(
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        if sync(loop, fs._isdir, source):
            raise self.NotSupported  # the filesystem's own mv (see above)
        progress.working_on(_name(source))
        sync(loop, fs._mv_file, source, target)

    def copy(
        self, fs: AbstractFileSystem, source: str, target: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        if not sync(loop, fs._isdir, source):
            progress.working_on(_name(source))
            sync(loop, fs._cp_file, source, target)
            return

        async def copy_one(item: tuple[str, str, int]) -> None:
            path, dest, size = item
            progress.check()
            progress.working_on(_name(path))
            await fs._cp_file(path, dest)
            progress.advance(files=1, bytes=size)

        files = _tree(fs, source, target, fs)
        self._each(loop, progress, files, copy_one, self.concurrency)

    def copy_between(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        loop = _loop_of(fs)
        if _loop_of(source_fs) is not loop:
            raise self.NotSupported  # run on different event loops
        if not sync(loop, source_fs._isdir, source):
            progress.working_on(_name(source))
            sync(
                loop, _copy_through_temp_async, source_fs, source, fs, target, progress
            )
            return

        async def copy_one(item: tuple[str, str, int]) -> None:
            path, dest, _size = item
            progress.check()
            progress.working_on(_name(path))
            await _copy_through_temp_async(source_fs, path, fs, dest, progress)
            progress.advance(files=1)

        files = _tree(source_fs, source, target, fs)
        self._each(loop, progress, files, copy_one, self.concurrency)

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        loop = _loop_of(fs)
        if not sync(loop, fs._isdir, path):
            progress.working_on(_name(path))
            sync(loop, fs._rm_file, path)
            return
        files = sync(loop, fs._find, path, detail=True)
        names = list(files)
        for start in range(0, len(names), self.delete_batch):
            progress.check()
            batch = names[start : start + self.delete_batch]
            progress.working_on(_name(batch[-1]))
            sync(loop, fs._rm, batch)
            progress.advance(
                files=len(batch), bytes=sum(files[n].get("size") or 0 for n in batch)
            )
        # The folders left, e.g. on filesystems with real folders.
        if sync(loop, fs._exists, path):
            sync(loop, fs._rm, path, recursive=True)

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        progress.working_on(_name(path))
        sync(loop, fs._get_file, path, local_path, callback=progress.callback())

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        progress.working_on(_name(path))
        sync(loop, fs._put_file, local_path, path, callback=progress.callback())

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        sync(_loop_of(fs), fs._makedirs, path, exist_ok=False)

    @staticmethod
    def _each(
        loop: asyncio.AbstractEventLoop,
        progress: Progress,
        items: Sequence[Any],
        act: Callable[[Any], Awaitable[None]],
        batch: int,
    ) -> None:
        """Run ``act(item)`` for all ``items``, ``batch`` at a time, on ``loop``.

        Each batch is awaited whole, so nothing runs on after a cancel or a
        failure, which are then raised (a cancel first).
        """
        for start in range(0, len(items), batch):
            progress.check()
            coros = [act(item) for item in items[start : start + batch]]
            results = sync(loop, _gather, coros)
            failures = [r for r in results if isinstance(r, BaseException)]
            for failure in failures:
                if isinstance(failure, OperationCancelled):
                    raise failure
            if failures:
                raise failures[0]


async def _gather(coros: list[Awaitable[None]]) -> list[Any]:
    return await asyncio.gather(*coros, return_exceptions=True)


def _loop_of(fs: AbstractFileSystem) -> asyncio.AbstractEventLoop:
    """The event loop to run ``fs``'s coroutines on. Raises
    ``FileSystemOperations.NotSupported`` if it is not an async filesystem
    usable from another thread."""
    if not isinstance(fs, AsyncFileSystem) or fs.asynchronous:
        raise FileSystemOperations.NotSupported
    return fs.loop


async def _copy_through_temp_async(
    source_fs: AsyncFileSystem,
    path: str,
    fs: AsyncFileSystem,
    target: str,
    progress: Progress,
) -> None:
    """``_copy_through_temp``, with the filesystems' coroutines."""
    handle, temp_path = tempfile.mkstemp(prefix="jse-copy-")
    os.close(handle)
    try:
        await source_fs._get_file(path, temp_path, callback=progress.callback())
        progress.check()
        await fs._put_file(temp_path, target, callback=progress.callback(count=False))
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_path)


class OperationChain:
    """Calls an operation on the first of ``operations`` that implements it
    (see the module docstring). Unless ``operations`` has an
    ``FsspecOperations``, ``AsyncFsspecOperations`` and ``FsspecOperations``
    come last, in that order."""

    def __init__(self, operations: Sequence[FileSystemOperations] = ()) -> None:
        self.operations = list(operations)
        if not any(type(o) is FsspecOperations for o in self.operations):
            self.operations += [AsyncFsspecOperations(), FsspecOperations()]

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


def _name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _tree(
    source_fs: AbstractFileSystem,
    source: str,
    target: str,
    fs: AbstractFileSystem,
) -> list[tuple[str, str, int]]:
    """(file, its target, size) for each file in folder ``source``, creating
    the target folders as needed (empty folders are not copied, as object
    stores have none)."""
    fs.makedirs(target, exist_ok=True)
    made = {target.rstrip("/")}
    out = []
    root = source.rstrip("/")
    for path, info in source_fs.find(source, detail=True).items():
        relative = path.rstrip("/")[len(root) :].lstrip("/")
        dest = f"{target.rstrip('/')}/{relative}"
        parent = dest.rsplit("/", 1)[0]
        if parent not in made:
            fs.makedirs(parent, exist_ok=True)
            made.add(parent)
        out.append((path, dest, info.get("size") or 0))
    return out


def _copy_through_temp(
    source_fs: AbstractFileSystem,
    path: str,
    fs: AbstractFileSystem,
    target: str,
    progress: Progress,
) -> None:
    """Copy one file between filesystems through a local temporary file, so a
    failed (or cancelled) copy never leaves a partial file in the storage."""
    handle, temp_path = tempfile.mkstemp(prefix="jse-copy-")
    os.close(handle)
    try:
        source_fs.get_file(path, temp_path, callback=progress.callback())
        progress.check()
        fs.put_file(temp_path, target, callback=progress.callback(count=False))
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_path)
