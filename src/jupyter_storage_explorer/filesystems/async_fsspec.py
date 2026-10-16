"""File operations with the coroutines of asynchronous fsspec filesystems
(s3fs, gcsfs, adlfs, ...), many files at a time."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from typing import TYPE_CHECKING, Any

from fsspec.asyn import AsyncFileSystem, sync
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.filesystems._common import (
    measure_by_folder,
    measure_file,
    measure_found,
    prepare_folder_copy,
    remove_emptied_folder,
)
from jupyter_storage_explorer.operations import (
    FileSystemOperations,
    OperationCancelled,
    same_filesystem,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.operations import Measurement, Progress


class AsyncFsspecOperations(FileSystemOperations):
    """Every operation on asynchronous fsspec filesystems (s3fs, gcsfs, adlfs,
    HTTP, ...), many files at a time: their coroutine methods (``_cp_file``,
    ``_mv_file``, ``_rm``, ``_get_file``, ...) run on the filesystem's event
    loop with ``fsspec.asyn.sync``, in batches of ``concurrency`` files.
    Object stores take about as long for a small file as for none, so moving,
    copying and deleting folders of many files is much faster than one file
    at a time.

    Other filesystems (and async ones made for use within a running event
    loop, ``asynchronous=True``) raise ``FileSystemOperations.NotSupported``,
    for ``FsspecOperations`` to do them, as do copies and moves between
    filesystems run on different event loops. Storages that rename a folder
    in one step are better moved by ``AtomicMoveOperation``, put before.

    A cancel takes effect between batches, and within a batch for files not
    yet started and transfers under way.

    Parameters
    ----------
    concurrency : int
        Files moved, copied (or downloaded) at a time.
    delete_batch : int
        Files deleted per ``_rm`` call: object stores delete many in one
        request (S3: up to 1,000).
    """

    def __init__(self, concurrency: int = 32, delete_batch: int = 1000) -> None:
        self.concurrency = concurrency
        self.delete_batch = delete_batch

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
    ) -> None:
        loop = _common_loop(source_fs, target_fs)
        same = same_filesystem(source_fs, target_fs)

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
    ) -> None:
        loop = _common_loop(source_fs, target_fs)
        same = same_filesystem(source_fs, target_fs)

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
        files = sync(loop, fs._find, path, detail=True)
        names = list(files)
        for start in range(0, len(names), self.delete_batch):
            progress.check()
            batch = names[start : start + self.delete_batch]
            progress.working_on(_paths.basename(batch[-1]))
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
        """``FileSystemOperations._copy_file``, with the filesystems'
        coroutines, run on their event loop: override it to copy files
        between two filesystems another way.

        Parameters
        ----------
        source_fs, path, target_fs, target, progress
            As for ``FileSystemOperations._copy_file``.
        """
        handle, temp_path = tempfile.mkstemp(prefix="jse-copy-")
        os.close(handle)
        try:
            await source_fs._get_file(path, temp_path, callback=progress.callback())
            progress.check()
            await target_fs._put_file(
                temp_path, target, callback=progress.callback(count=False)
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_path)

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
