"""Copying one file between two filesystems without a local temporary file.

A small file is read whole, then written in one call: object stores never
show it half written. A larger one streams, block by block, while a thread
reads the next blocks: reading and writing overlap, and the kernel's disk
holds nothing, so files larger than its disk can be copied.

A failed or cancelled stream leaves no partial file where fsspec's writable
files can be abandoned (``AbstractBufferedFile``: s3fs, gcsfs, adlfs, ...):
their last part is never sent, and ``discard()`` drops the parts sent. On
other filesystems, e.g. a local disk, what was written is deleted. A file
that was there before is never deleted, as an object store keeps it until a
write completes; on a local disk, it is then spoiled, as with ``put_file``.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from typing import TYPE_CHECKING

from fsspec.spec import AbstractBufferedFile

try:
    from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper
except ImportError:  # fsspec before 2024.12
    AsyncFileSystemWrapper = ()  # an isinstance() matching nothing

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import IO

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.filesystems.operation import Progress

# Files up to this size are read whole and written in one call.
SMALL = 8 * 2**20
# The blocks a stream reads, and how many it reads ahead of the writes:
# with the target's own buffer, about what a stream holds in memory.
BLOCK = 8 * 2**20
AHEAD = 4


def copy_file(
    source_fs: AbstractFileSystem,
    path: str,
    target_fs: AbstractFileSystem,
    target: str,
    progress: Progress,
) -> None:
    """Copy file ``path`` of ``source_fs`` to ``target`` of ``target_fs``,
    reporting its bytes to ``progress`` as they are written."""
    source_fs = _with_files(source_fs)
    with source_fs.open(path, "rb") as source:
        size = getattr(source, "size", None)
        if size is None:
            size = source_fs.size(path)
        if size is not None and size <= SMALL:
            data = source.read()
            progress.check()
            target_fs.pipe_file(target, data)
            progress.advance(bytes=len(data))
            return
        stream(source, target_fs, target, progress)


def stream(
    source: IO[bytes], target_fs: AbstractFileSystem, target: str, progress: Progress
) -> None:
    """Write what is left to read of ``source`` to ``target``, block by block."""
    target_fs = _with_files(target_fs)
    existed = target_fs.exists(target)
    out = target_fs.open(target, "wb")
    try:
        written = 0
        for block in _read_ahead(source):
            progress.check()
            out.write(block)
            written += len(block)
            progress.advance(bytes=len(block))
        progress.check()
        out.close()  # sends the last part, and completes the file
        # A file of another size means bytes were lost, e.g. by a writable
        # file that is not implemented: an error, never a silent loss.
        if (size := target_fs.size(target)) != written:
            raise OSError(f"{target}: {size} bytes written of {written}")
    except BaseException:
        _abandon(out)
        if not existed:
            with contextlib.suppress(Exception):
                if target_fs.exists(target):
                    target_fs.rm_file(target)
        raise


def _with_files(fs: AbstractFileSystem) -> AbstractFileSystem:
    """``fs``, or the filesystem it wraps if its files cannot be used: those
    of fsspec's ``AsyncFileSystemWrapper`` are fsspec's base class, which
    cannot read and drops what is written."""
    return fs.sync_fs if isinstance(fs, AsyncFileSystemWrapper) else fs


def _abandon(out: IO[bytes]) -> None:
    """Close ``out`` without completing the file, where fsspec lets it. Also
    after a failed ``close``, whose upload ``discard()`` may still drop."""
    if isinstance(out, AbstractBufferedFile):
        with contextlib.suppress(Exception):
            out.discard()
        # Not ``closed`` itself: ``close`` also releases what the file holds,
        # e.g. adlfs' client. ``forced`` tells it the last part was sent.
        out.forced = True
    with contextlib.suppress(Exception):
        out.close()


def _read_ahead(source: IO[bytes]) -> Iterator[bytes]:
    """``source``'s blocks, up to ``AHEAD`` read by a thread ahead of the one
    the caller is writing. Once the caller stops, the thread ends after the
    read under way."""
    blocks: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=AHEAD)
    stop = threading.Event()

    def put(item: bytes | BaseException) -> None:
        while not stop.is_set():
            with contextlib.suppress(queue.Full):
                blocks.put(item, timeout=0.1)
                return

    def read() -> None:
        try:
            while not stop.is_set():
                block = source.read(BLOCK)
                put(block)
                if not block:
                    return
        except BaseException as exc:
            put(exc)

    reader = threading.Thread(target=read, name="jse-read-ahead", daemon=True)
    reader.start()
    try:
        while True:
            item = blocks.get()
            if isinstance(item, BaseException):
                raise item
            if not item:
                return
            yield item
    finally:
        stop.set()
        reader.join()
