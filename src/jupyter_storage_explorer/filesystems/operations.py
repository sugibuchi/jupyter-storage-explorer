"""The predefined file operations (see operation.py): with fsspec's
synchronous API, for any filesystem (``FsspecOperations``); renames in one
step (``AtomicMoveOperation``); and with the coroutines of asynchronous
filesystems (s3fs, gcsfs, adlfs, ...), many files at a time
(``AsyncFsspecOperations``).
"""

from __future__ import annotations

import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from fsspec.asyn import AsyncFileSystem, sync
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.filesystems import _streaming
from jupyter_storage_explorer.filesystems._common import (
    measure_by_folder,
    measure_file,
    measure_found,
    prepare_folder_copy,
    remove_emptied_folder,
)
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    OperationCancelled,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.filesystems.operation import Measurement, Progress

__all__ = [
    "AsyncFsspecOperations",
    "AtomicMoveOperation",
    "FsspecOperations",
]


class FsspecOperations(FileSystemOperations):
    """Every operation, with fsspec's API: works on any filesystem.

    Folders are moved, copied and deleted file by file (deletions in
    batches), so progress shows and a cancel takes effect between files.
    Within a filesystem, each file is moved with its ``mv`` (a rename where
    the storage has one; a copy then a delete on object stores) and copied
    with its ``cp_file``. Between filesystems, files go through ``_copy_file``
    and ``_move_file`` (by default, streamed through the kernel), so a
    cancel leaves each file in one place.
    """

    # Files deleted per request when deleting a folder: object stores delete
    # many files in one request, and cancelling takes effect between batches.
    DELETE_BATCH = 100

    def measure(
        self, fs: AbstractFileSystem, path: str, progress: Progress | None = None
    ) -> Measurement:
        """One recursive listing (``find``); with ``progress``, one ``ls`` per
        folder, so that it shows and can be cancelled."""
        info = fs.info(path)
        if info.get("type") != "directory":
            return measure_file(info, progress)
        if progress is None:
            return measure_found(path, fs.find(path, withdirs=True, detail=True))

        def list_folders(paths: Sequence[str]) -> list[Any]:
            try:
                return [fs.ls(paths[0], detail=True)]
            except Exception as exc:
                return [exc]

        return measure_by_folder(path, list_folders, progress)

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

        def move_file(path: str, dest: str) -> None:
            if same:
                source_fs.mv(path, dest)
            else:
                self._move_file(source_fs, path, target_fs, dest, progress)

        if not source_fs.isdir(source):
            progress.working_on(_paths.basename(source))
            move_file(source, target)
            return
        for path, dest, size in prepare_folder_copy(
            source_fs, source, target_fs, target
        ):
            progress.check()
            progress.working_on(_paths.basename(path))
            move_file(path, dest)
            # Transfers between filesystems report their bytes as they go.
            progress.advance(files=1, bytes=size if same else 0)
        remove_emptied_folder(source_fs, source)

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

        def copy_file(path: str, dest: str) -> None:
            if same:
                source_fs.cp_file(path, dest)
            else:
                self._copy_file(source_fs, path, target_fs, dest, progress)

        if not source_fs.isdir(source):
            progress.working_on(_paths.basename(source))
            copy_file(source, target)
            return
        for path, dest, size in prepare_folder_copy(
            source_fs, source, target_fs, target
        ):
            progress.check()
            progress.working_on(_paths.basename(path))
            copy_file(path, dest)
            progress.advance(files=1, bytes=size if same else 0)

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        if not fs.isdir(path):
            progress.working_on(_paths.basename(path))
            fs.rm_file(path)
            return
        names = fs.find(path)
        progress.add_total(files=len(names))
        for start in range(0, len(names), self.DELETE_BATCH):
            progress.check()
            batch = names[start : start + self.DELETE_BATCH]
            progress.working_on(_paths.basename(batch[-1]))
            self._rm_batch(fs, batch)
            progress.advance(files=len(batch))
        # The folders left, e.g. on local disks.
        if fs.exists(path):
            fs.rm(path, recursive=True)

    @staticmethod
    def _rm_batch(fs: AbstractFileSystem, batch: list[str]) -> None:
        """Delete the files ``batch`` names, in one request where the
        filesystem can. fsspec's ``rm`` takes a list of paths, but some
        filesystems' take one path only (huggingface_hub's ``HfFileSystem``
        raises ValueError): their files are then deleted one by one, skipping
        those the refused call may have deleted already."""
        try:
            fs.rm(batch)
        except (TypeError, ValueError):
            for name in batch:
                with contextlib.suppress(FileNotFoundError):
                    fs.rm_file(name)

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        progress.working_on(_paths.basename(path))
        fs.get_file(path, local_path, callback=progress.callback())

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        progress.working_on(_paths.basename(path))
        fs.put_file(local_path, path, callback=progress.callback())

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        fs.makedirs(path, exist_ok=False)


class AtomicMoveOperation(FileSystemOperations):
    """Moves within a filesystem whose own ``mv`` moves a folder in one step,
    e.g. a rename on a local disk: quicker than file by file, and never left
    half done, though its progress then shows no file until the end.

    Only ``move``, within one filesystem of ``protocols`` (or a
    ``DirFileSystem`` over one); everything else raises
    ``FileSystemOperations.NotSupported``, for the next operations object.

    Parameters
    ----------
    protocols : iterable of str, default ("file", "local", "memory")
        The protocols of the filesystems to move with their ``mv``. Add only
        those whose ``mv`` renames folders, e.g. ``"sftp"`` or ``"hdfs"``,
        not object stores, whose ``mv`` copies then deletes every file.

    Examples
    --------
    >>> StorageExplorer(
    ...     filesystems={...},
    ...     operations=[
    ...         AtomicMoveOperation([*AtomicMoveOperation.PROTOCOLS, "sftp"]),
    ...         AsyncFsspecOperations(),
    ...         FsspecOperations(),
    ...     ],
    ... )
    """

    PROTOCOLS = ("file", "local", "memory")

    def __init__(self, protocols: Iterable[str] = PROTOCOLS) -> None:
        self.protocols = frozenset(protocols)

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
        if not same or not self._renames(source_fs):
            raise self.NotSupported
        progress.working_on(_paths.basename(source))
        source_fs.mv(source, target, recursive=source_fs.isdir(source))

    def _renames(self, fs: AbstractFileSystem) -> bool:
        """Whether ``fs`` is one of ``protocols``, itself or under a DirFileSystem."""
        if isinstance(fs, DirFileSystem):
            return self._renames(fs.fs)
        protocols = (fs.protocol,) if isinstance(fs.protocol, str) else fs.protocol
        return not self.protocols.isdisjoint(protocols)


class AsyncFsspecOperations(FileSystemOperations):
    """Every operation on asynchronous fsspec filesystems (s3fs, gcsfs, adlfs,
    HTTP, ...), many files at a time: their coroutine methods (``_cp_file``,
    ``_mv_file``, ``_rm``, ``_get_file``, ...) run on the filesystem's event
    loop with ``fsspec.asyn.sync``, ``concurrency`` files at a time, each
    starting as soon as another ends. Object stores take about as long for a
    small file as for none, so moving, copying and deleting folders of many
    files is much faster than one file at a time.

    Other filesystems (and async ones made for use within a running event
    loop, ``asynchronous=True``) raise ``FileSystemOperations.NotSupported``,
    for ``FsspecOperations`` to do them, as do copies and moves between
    filesystems run on different event loops. Storages that rename a folder
    in one step are better moved by ``AtomicMoveOperation``, put before.

    A cancel stops files from starting, and transfers under way. Files being
    moved or copied within a filesystem finish first.

    Parameters
    ----------
    concurrency : int
        Files moved, copied (or downloaded) at a time.
    delete_batch : int
        Files deleted per ``_rm`` call: object stores delete many in one
        request (S3: up to 1,000).
    streams : int
        Files larger than 8 MiB copied between filesystems at a time, of
        ``concurrency``. Each holds up to about 40 MiB in memory, besides
        the target filesystem's own buffer.
    """

    def __init__(
        self, concurrency: int = 32, delete_batch: int = 1000, streams: int = 4
    ) -> None:
        self.concurrency = concurrency
        self.delete_batch = delete_batch
        self.streams = streams
        # Streams use fsspec's synchronous files, which cannot run on the
        # filesystems' event loop; the pool's size bounds their memory.
        self._streams = ThreadPoolExecutor(streams, thread_name_prefix="jse-stream")

    def measure(
        self, fs: AbstractFileSystem, path: str, progress: Progress | None = None
    ) -> Measurement:
        """One recursive listing (``_find``: on object stores, a listing of
        every key under the folder, a thousand per request); with
        ``progress``, one ``_ls`` per folder, ``concurrency`` folders at a
        time, so that it shows and can be cancelled."""
        loop = _loop_of(fs)
        info = sync(loop, fs._info, path)
        if info.get("type") != "directory":
            return measure_file(info, progress)
        if progress is None:
            found = sync(loop, fs._find, path, withdirs=True, detail=True)
            return measure_found(path, found)

        def list_folders(paths: Sequence[str]) -> list[Any]:
            async def listings() -> list[Any]:
                return await asyncio.gather(
                    *(fs._ls(p, detail=True) for p in paths), return_exceptions=True
                )

            return sync(loop, listings)

        return measure_by_folder(path, list_folders, progress, self.concurrency)

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
        loop = _common_loop(source_fs, target_fs)

        async def move_file(path: str, dest: str) -> None:
            if same:
                await source_fs._mv_file(path, dest)
            else:
                await self._move_file_async(source_fs, path, target_fs, dest, progress)

        if not sync(loop, source_fs._isdir, source):
            progress.working_on(_paths.basename(source))
            sync(loop, move_file, source, target)
            return

        async def move_one(item: tuple[str, str, int]) -> None:
            path, dest, size = item
            progress.check()
            progress.working_on(_paths.basename(path))
            await move_file(path, dest)
            # Transfers between filesystems report their bytes as they go.
            progress.advance(files=1, bytes=size if same else 0)

        files = prepare_folder_copy(source_fs, source, target_fs, target)
        self._each(loop, progress, files, move_one, self.concurrency)
        remove_emptied_folder(source_fs, source)

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
        loop = _common_loop(source_fs, target_fs)

        async def copy_file(path: str, dest: str) -> None:
            if same:
                await source_fs._cp_file(path, dest)
            else:
                await self._copy_file_async(source_fs, path, target_fs, dest, progress)

        if not sync(loop, source_fs._isdir, source):
            progress.working_on(_paths.basename(source))
            sync(loop, copy_file, source, target)
            return

        async def copy_one(item: tuple[str, str, int]) -> None:
            path, dest, size = item
            progress.check()
            progress.working_on(_paths.basename(path))
            await copy_file(path, dest)
            progress.advance(files=1, bytes=size if same else 0)

        files = prepare_folder_copy(source_fs, source, target_fs, target)
        self._each(loop, progress, files, copy_one, self.concurrency)

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        loop = _loop_of(fs)
        if not sync(loop, fs._isdir, path):
            progress.working_on(_paths.basename(path))
            sync(loop, fs._rm_file, path)
            return
        names = sync(loop, fs._find, path)
        progress.add_total(files=len(names))
        for start in range(0, len(names), self.delete_batch):
            progress.check()
            batch = names[start : start + self.delete_batch]
            progress.working_on(_paths.basename(batch[-1]))
            sync(loop, fs._rm, batch)
            progress.advance(files=len(batch))
        # The folders left, e.g. on filesystems with real folders.
        if sync(loop, fs._exists, path):
            sync(loop, fs._rm, path, recursive=True)

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        progress.working_on(_paths.basename(path))
        sync(loop, fs._get_file, path, local_path, callback=progress.callback())

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        loop = _loop_of(fs)
        progress.working_on(_paths.basename(path))
        sync(loop, fs._put_file, local_path, path, callback=progress.callback())

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        sync(_loop_of(fs), fs._makedirs, path, exist_ok=False)

    async def _copy_file_async(
        self,
        source_fs: AbstractFileSystem,
        path: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """``FileSystemOperations._copy_file``, run on the filesystems' event
        loop: override it to copy files between two filesystems another way.

        A file up to 8 MiB is read whole, then written, with the filesystems'
        coroutines. A larger one streams as ``_copy_file`` does, in a thread,
        at most ``streams`` at a time.

        Parameters
        ----------
        source_fs, path, target_fs, target, progress
            As for ``FileSystemOperations._copy_file``.
        """
        size = (await source_fs._info(path)).get("size")
        if size is not None and size <= _streaming.SMALL:
            data = await source_fs._cat_file(path)
            progress.check()
            await target_fs._pipe_file(target, data)
            progress.advance(bytes=len(data))
            return
        await asyncio.get_running_loop().run_in_executor(
            self._streams,
            _streaming.copy_file,
            source_fs,
            path,
            target_fs,
            target,
            progress,
        )

    async def _move_file_async(
        self,
        source_fs: AbstractFileSystem,
        path: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        """``FileSystemOperations._move_file``, with the filesystems'
        coroutines: ``_copy_file_async``, then the source deleted.

        Parameters
        ----------
        source_fs, path, target_fs, target, progress
            As for ``FileSystemOperations._move_file``.
        """
        await self._copy_file_async(source_fs, path, target_fs, target, progress)
        try:
            await source_fs._rm_file(path)
        except Exception as exc:
            raise self._not_removed(path, exc) from exc

    @staticmethod
    def _each(
        loop: asyncio.AbstractEventLoop,
        progress: Progress,
        items: Sequence[Any],
        act: Callable[[Any], Awaitable[None]],
        concurrency: int,
    ) -> None:
        """Run ``act(item)`` for all ``items`` on ``loop``, ``concurrency`` at a
        time. Each item starts as soon as another ends, so a large file never
        holds up the small ones.

        After a cancel or a failure, no item starts, and those running are
        awaited. Then the failure is raised, a cancel first.
        """
        progress.check()
        sync(loop, _sliding_window, items, act, concurrency)


async def _sliding_window(
    items: Iterable[Any], act: Callable[[Any], Awaitable[None]], concurrency: int
) -> None:
    """``AsyncFsspecOperations._each``'s work, on the filesystem's loop."""
    pending = iter(items)
    running: set[asyncio.Future[None]] = set()
    failures: list[BaseException] = []

    def fill() -> None:
        while not failures and len(running) < concurrency:
            item = next(pending, _END)
            if item is _END:
                return
            running.add(asyncio.ensure_future(act(item)))

    fill()
    while running:
        done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
        running.difference_update(done)
        failures.extend(e for task in done if (e := task.exception()) is not None)
        fill()
    for failure in failures:
        if isinstance(failure, OperationCancelled):
            raise failure
    if failures:
        raise failures[0]


_END = object()


def _loop_of(fs: AbstractFileSystem) -> asyncio.AbstractEventLoop:
    """The event loop to run ``fs``'s coroutines on. Raises
    ``FileSystemOperations.NotSupported`` if it is not an async filesystem
    usable from another thread."""
    if not isinstance(fs, AsyncFileSystem) or fs.asynchronous:
        raise FileSystemOperations.NotSupported
    if isinstance(fs, DirFileSystem):
        # Async by its class, whatever it wraps: its coroutines call those of
        # the filesystem it wraps, which a local or memory one does not have.
        return _loop_of(fs.fs)
    return fs.loop


def _common_loop(
    source_fs: AbstractFileSystem, target_fs: AbstractFileSystem
) -> asyncio.AbstractEventLoop:
    """The event loop both filesystems run on; NotSupported if they are not
    both async, or run on different loops."""
    loop = _loop_of(target_fs)
    if _loop_of(source_fs) is not loop:
        raise FileSystemOperations.NotSupported
    return loop


def default_operations() -> list[FileSystemOperations]:
    """The file operations tried after an explorer's ``operations``.

    Returns
    -------
    list of FileSystemOperations
        New objects each time: ``AtomicMoveOperation`` (moves in one step
        on local disks), ``AsyncFsspecOperations`` (asynchronous fsspec
        filesystems such as s3fs, gcsfs and adlfs, many files at a time),
        then ``FsspecOperations`` (everything else, with fsspec). The last
        does every operation, so the explorer can always do them.
    """
    return [AtomicMoveOperation(), AsyncFsspecOperations(), FsspecOperations()]
