"""filesystems/_streaming.py: copies between filesystems without a local
temporary file; no partial file left after a failure or a cancel."""

from __future__ import annotations

import io

import fsspec
import pytest
from fsspec import AbstractFileSystem
from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper
from fsspec.spec import AbstractBufferedFile

from jupyter_storage_explorer._jobs.progress import JobProgress
from jupyter_storage_explorer.filesystems import _streaming
from jupyter_storage_explorer.filesystems.operation import OperationCancelled
from jupyter_storage_explorer.filesystems.operations import (
    AsyncFsspecOperations,
    FsspecOperations,
)

DATA = bytes(range(256)) * 4  # 1 KiB


@pytest.fixture
def small_blocks(monkeypatch):
    """Files over 100 bytes stream, in blocks of 64, two read ahead."""
    monkeypatch.setattr(_streaming, "SMALL", 100)
    monkeypatch.setattr(_streaming, "BLOCK", 64)
    monkeypatch.setattr(_streaming, "AHEAD", 2)


def cancelled_after(nbytes: int) -> JobProgress:
    """A progress the user cancels once ``nbytes`` are copied."""
    progress = JobProgress(on_change=lambda: None)
    progress._on_change = lambda: progress.bytes_done >= nbytes and progress.cancel()
    return progress


class PartsFile(AbstractBufferedFile):
    """A writable file as object stores' are: parts sent as the buffer fills,
    the file complete only once the last is sent."""

    def _initiate_upload(self) -> None:
        self.parts: list[bytes] = []

    def _upload_chunk(self, final: bool = False) -> bool:
        self.parts.append(self.buffer.getvalue())
        if final:
            self.fs.files[self.path] = b"".join(self.parts)
        return True

    def discard(self) -> None:
        self.fs.discarded.append(self.path)


class PartsFileSystem(AbstractFileSystem):
    """Writes ``PartsFile``s of 64-byte parts; keeps the files completed."""

    cachable = False
    protocol = "parts"

    def __init__(self) -> None:
        super().__init__()
        self.files: dict[str, bytes] = {}
        self.discarded: list[str] = []

    def _open(self, path, mode="rb", block_size=None, autocommit=True, **kwargs):
        return PartsFile(self, path, mode, block_size=64, autocommit=autocommit)

    def info(self, path, **kwargs):
        path = self._strip_protocol(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        return {"name": path, "size": len(self.files[path]), "type": "file"}

    def rm_file(self, path):
        del self.files[self._strip_protocol(path)]


class TestCopyFile:
    def test_a_small_file_in_one_write(self, memfs):
        memfs.pipe_file("/a.bin", DATA)
        target = PartsFileSystem()
        progress = JobProgress()
        _streaming.copy_file(memfs, "/a.bin", target, "/b.bin", progress)
        assert target.files == {"/b.bin": DATA}
        assert progress.bytes_done == len(DATA)

    def test_a_large_file_streamed(self, memfs, small_blocks):
        memfs.pipe_file("/a.bin", DATA)
        target = PartsFileSystem()
        progress = JobProgress()
        _streaming.copy_file(memfs, "/a.bin", target, "/b.bin", progress)
        assert target.files == {"/b.bin": DATA}
        assert progress.bytes_done == len(DATA)

    def test_cancelled_object_store_file_never_completed(self, memfs, small_blocks):
        memfs.pipe_file("/a.bin", DATA)
        target = PartsFileSystem()
        with pytest.raises(OperationCancelled):
            _streaming.copy_file(
                memfs, "/a.bin", target, "/b.bin", cancelled_after(200)
            )
        # Parts were sent, but not the last: discarded, not completed.
        assert target.files == {}
        assert target.discarded == ["/b.bin"]

    def test_cancelled_local_file_deleted(self, memfs, small_blocks, tmp_path):
        memfs.pipe_file("/a.bin", DATA)
        local = fsspec.filesystem("file")
        target = (tmp_path / "b.bin").as_posix()
        with pytest.raises(OperationCancelled):
            _streaming.copy_file(memfs, "/a.bin", local, target, cancelled_after(200))
        assert not local.exists(target)

    def test_a_file_replaced_never_deleted(self, memfs, small_blocks):
        # An object store keeps it until the new one is complete.
        memfs.pipe_file("/a.bin", DATA)
        target = PartsFileSystem()
        target.files["/b.bin"] = b"before"
        with pytest.raises(OperationCancelled):
            _streaming.copy_file(
                memfs, "/a.bin", target, "/b.bin", cancelled_after(200)
            )
        assert target.files == {"/b.bin": b"before"}

    def test_bytes_lost_raised(self, memfs, small_blocks):
        # fsspec's base class of files, as AsyncFileSystemWrapper's: it sends
        # nothing, which must fail the copy, never pass for one.
        class Dropping(PartsFileSystem):
            def _open(self, path, mode="rb", **kwargs):
                return AbstractBufferedFile(self, path, mode, block_size=64)

        memfs.pipe_file("/a.bin", DATA)
        with pytest.raises(OSError):
            _streaming.copy_file(memfs, "/a.bin", Dropping(), "/b.bin", JobProgress())

    def test_a_read_error_raised(self, small_blocks):
        class Failing(io.BytesIO):
            def read(self, size=-1):
                if self.tell() >= 128:
                    raise OSError("connection reset")
                return super().read(size)

        target = PartsFileSystem()
        with pytest.raises(OSError, match="connection reset"):
            _streaming.stream(Failing(DATA), target, "/b.bin", JobProgress())
        assert target.files == {}


@pytest.mark.parametrize("ops", [FsspecOperations(), AsyncFsspecOperations()])
@pytest.mark.parametrize("size", [50, len(DATA)])  # read whole, streamed
def test_copies_between_filesystems(memfs, small_blocks, ops, size):
    memfs.pipe({"/src/a.bin": DATA[:size], "/src/sub/b.bin": DATA[:size]})
    if isinstance(ops, AsyncFsspecOperations):
        source, target = AsyncFileSystemWrapper(memfs), AsyncFileSystemWrapper(memfs)
    else:
        source, target = memfs, fsspec.filesystem("memory", skip_instance_cache=True)
    progress = JobProgress()
    ops.copy(source, "/src", target, "/dst", progress, same=False)
    assert memfs.cat(["/dst/a.bin", "/dst/sub/b.bin"]) == {
        "/dst/a.bin": DATA[:size],
        "/dst/sub/b.bin": DATA[:size],
    }
    assert progress.bytes_done == 2 * size
