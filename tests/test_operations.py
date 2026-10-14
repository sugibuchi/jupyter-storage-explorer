"""operations.py, filesystems/ and jobs.py: file operations with progress and cancellation, run as jobs."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import fsspec
import pytest
from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import jobs
from jupyter_storage_explorer.filesystems import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
)
from jupyter_storage_explorer.jobs import JobRunner
from jupyter_storage_explorer.operations import (
    FileSystemOperations,
    Measurement,
    OperationCancelled,
    OperationChain,
    Progress,
    measure_file_info,
    same_filesystem,
)


@pytest.fixture
def tree(memfs):
    """/src: three files, one in a subfolder."""
    memfs.pipe({"/src/a.txt": b"aaaa", "/src/b.txt": b"bb", "/src/sub/c.txt": b"c"})
    return memfs


class Recorder(Progress):
    """A Progress keeping the names worked on."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []

    def working_on(self, name: str) -> None:
        super().working_on(name)
        self.names.append(name)


class TestProgress:
    def test_items_counted_when_done(self):
        progress = Progress()
        progress.add_total(files=5, bytes=100)
        progress.begin_item(3, 60)
        progress.advance(files=1, bytes=10)  # reported only partly...
        progress.end_item()  # ...the rest is counted
        snap = progress.snapshot()
        assert (snap["files_done"], snap["bytes_done"]) == (3, 60)

    def test_callback_counts_bytes_and_stops(self):
        progress = Progress()
        callback = progress.callback()
        callback.relative_update(10)
        callback.relative_update(5)
        assert progress.bytes_done == 15
        progress.callback(count=False).relative_update(100)
        assert progress.bytes_done == 15
        progress.cancel()
        with pytest.raises(OperationCancelled):
            callback.relative_update(1)

    def test_on_change(self):
        calls = []
        progress = Progress(on_change=lambda: calls.append(1))
        progress.advance(files=1)
        progress.working_on("a")
        assert len(calls) == 2


@pytest.fixture(params=["sync", "async"])
def measuring(request):
    """The default operations, and how to give them a filesystem:
    FsspecOperations on it, or AsyncFsspecOperations on it as an asynchronous
    filesystem (wrapped when called, as the wrapper binds its methods then)."""
    if request.param == "sync":
        return FsspecOperations(), lambda fs: fs
    return AsyncFsspecOperations(concurrency=2), AsyncFileSystemWrapper


class TestMeasure:
    """measure(), by both default operations: one recursive listing without a
    progress (before a job), folder by folder with one ("Properties")."""

    def counts(self, measurement: Measurement) -> tuple[int, int, int]:
        return measurement.files, measurement.bytes, measurement.folders

    def test_a_folder(self, measuring, tree):
        ops, wrap = measuring
        fs = wrap(tree)
        assert self.counts(ops.measure(fs, "/src")) == (3, 7, 1)
        progress = Recorder()
        measurement = ops.measure(fs, "/src", progress)
        assert self.counts(measurement) == (3, 7, 1)
        assert measurement.complete
        assert (progress.files_done, progress.bytes_done) == (3, 7)
        assert sorted(progress.names) == ["src", "sub"]  # the folders listed

    def test_a_file(self, measuring, tree):
        ops, wrap = measuring
        measurement = ops.measure(wrap(tree), "/src/a.txt")
        assert self.counts(measurement) == (1, 4, 0)
        assert measurement.oldest == measurement.newest
        assert measurement.oldest[1] == "/src/a.txt"

    def test_oldest_and_newest(self, measuring, tmp_path):
        ops, wrap = measuring
        for name, day in {"a.txt": 3, "b.txt": 1, "sub/c.txt": 2}.items():
            path = tmp_path / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"x")
            os.utime(path, (day * 1000, day * 1000))
        fs = wrap(fsspec.filesystem("file"))
        top = tmp_path.as_posix()
        for measurement in (ops.measure(fs, top), ops.measure(fs, top, Progress())):
            assert measurement.oldest == (1000, f"{top}/b.txt")
            assert measurement.newest == (3000, f"{top}/a.txt")

    def test_folders_that_cannot_be_listed(self, measuring, tree, monkeypatch):
        ops, wrap = measuring
        ls = tree.ls

        def refusing(path: str, **kwargs: Any) -> Any:
            if path.rstrip("/") == "/src/sub":
                raise PermissionError(13, "Access denied", path)
            return ls(path, **kwargs)

        monkeypatch.setattr(tree, "ls", refusing)
        measurement = ops.measure(wrap(tree), "/src", Progress())
        assert self.counts(measurement) == (2, 6, 1)
        assert measurement.errors == ["/src/sub: [Errno 13] Access denied: '/src/sub'"]

    def test_cancelled_with_what_was_found(self, measuring, tree):
        ops, wrap = measuring
        fs = wrap(tree)

        def cancel_once_files_found() -> None:
            if progress.files_done:
                progress.cancel()

        progress = Progress(on_change=cancel_once_files_found)
        measurement = ops.measure(fs, "/src", progress)
        assert not measurement.complete
        assert measurement.files == 2  # /src's files; /src/sub not listed


def test_measure_file_info():
    assert measure_file_info({"name": "/d/a/", "size": 4, "mtime": 5}) == Measurement(
        files=1, bytes=4, oldest=(5, "/d/a"), newest=(5, "/d/a")
    )
    assert measure_file_info({"name": "/d/b", "size": None}) == Measurement(files=1)


def test_measurements_merged():
    total = Measurement(files=1, bytes=4, oldest=(5, "a"), newest=(5, "a"))
    total.merge(
        Measurement(
            files=2, bytes=3, folders=1, oldest=(2, "b"), newest=(9, "c"), errors=["x"]
        )
    )
    assert total == Measurement(
        files=3, bytes=7, folders=1, oldest=(2, "b"), newest=(9, "c"), errors=["x"]
    )
    total.merge(Measurement(complete=False))
    assert not total.complete


class TestFsspecOperations:
    ops = FsspecOperations()

    def test_copy_folder_file_by_file(self, tree):
        progress = Recorder()
        self.ops.copy(tree, "/src", tree, "/dst", progress)
        assert tree.cat_file("/dst/sub/c.txt") == b"c"
        assert sorted(progress.names) == ["a.txt", "b.txt", "c.txt"]
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_copy_cancelled_between_files(self, tree):
        progress = Recorder()
        original = tree.cp_file

        def cp_then_cancel(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            progress.cancel()

        tree.cp_file = cp_then_cancel
        try:
            with pytest.raises(OperationCancelled):
                self.ops.copy(tree, "/src", tree, "/dst", progress)
        finally:
            del tree.cp_file
        assert len(tree.find("/dst")) == 1

    def test_copy_between_filesystems(self, tree, tmp_path):
        local = fsspec.filesystem("file")
        target = (tmp_path / "copy").as_posix()
        progress = Progress()
        self.ops.copy(tree, "/src", local, target, progress)
        assert (tmp_path / "copy" / "sub" / "c.txt").read_bytes() == b"c"
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_move_between_filesystems(self, tree, tmp_path):
        local = fsspec.filesystem("file")
        target = (tmp_path / "moved").as_posix()
        progress = Progress()
        self.ops.move(tree, "/src", local, target, progress)
        assert (tmp_path / "moved" / "sub" / "c.txt").read_bytes() == b"c"
        assert not tree.exists("/src")
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_move_between_cancelled_leaves_each_file_in_one_place(
        self, tree, tmp_path, monkeypatch
    ):
        local = fsspec.filesystem("file")
        progress = Progress()
        original = tree.rm_file

        def rm_then_cancel(path: str) -> None:
            original(path)
            progress.cancel()

        monkeypatch.setattr(tree, "rm_file", rm_then_cancel)
        with pytest.raises(OperationCancelled):
            self.ops.move(
                tree, "/src", local, (tmp_path / "moved").as_posix(), progress
            )
        moved = {p.name for p in (tmp_path / "moved").rglob("*.txt")}
        left = {p.rsplit("/", 1)[-1] for p in tree.find("/src")}
        assert len(moved) == 1 and len(left) == 2 and not moved & left

    def test_move_between_reports_a_source_not_deleted(
        self, tree, tmp_path, monkeypatch
    ):
        def read_only(path: str) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(tree, "rm_file", read_only)
        local, target = fsspec.filesystem("file"), (tmp_path / "a.txt").as_posix()
        with pytest.raises(OSError, match=r"a\.txt was copied, but not deleted"):
            self.ops.move(tree, "/src/a.txt", local, target, Progress())
        assert (tmp_path / "a.txt").read_bytes() == b"aaaa"

    def test_delete_folder_in_batches(self, tree, monkeypatch):
        monkeypatch.setattr(FsspecOperations, "DELETE_BATCH", 2)
        progress = Progress()
        self.ops.delete(tree, "/src", progress)
        assert not tree.exists("/src")
        assert progress.files_done == 3

    def test_move_folder_file_by_file(self, tree):
        progress = Recorder()
        self.ops.move(tree, "/src", tree, "/moved", progress)
        assert tree.cat_file("/moved/sub/c.txt") == b"c"
        assert not tree.exists("/src")
        assert sorted(progress.names) == ["a.txt", "b.txt", "c.txt"]
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_move_on_a_local_disk_leaves_no_folders(self, tmp_path):
        (tmp_path / "src" / "sub").mkdir(parents=True)
        (tmp_path / "src" / "sub" / "c.txt").write_bytes(b"c")
        local = fsspec.filesystem("file")
        source, target = (tmp_path / "src").as_posix(), (tmp_path / "moved").as_posix()
        self.ops.move(local, source, local, target, Progress())
        assert (tmp_path / "moved" / "sub" / "c.txt").read_bytes() == b"c"
        assert not (tmp_path / "src").exists()

    def test_mkdir(self, tree):
        self.ops.mkdir(tree, "/new")
        assert tree.isdir("/new")

    def test_copy_file_can_be_overridden(self, tree, tmp_path):
        """Copies and moves between filesystems go through _copy_file."""
        calls = []

        class ServerSide(FsspecOperations):
            def _copy_file(self, source_fs, path, target_fs, target, progress):
                calls.append(path)
                target_fs.pipe_file(target, source_fs.cat_file(path))

        local = fsspec.filesystem("file")
        target = (tmp_path / "copy").as_posix()
        ServerSide().copy(tree, "/src", local, target, Progress())
        ServerSide().move(tree, "/src/a.txt", local, f"{target}/moved.txt", Progress())
        assert sorted(calls) == [
            "/src/a.txt",
            "/src/a.txt",
            "/src/b.txt",
            "/src/sub/c.txt",
        ]
        assert (tmp_path / "copy" / "moved.txt").read_bytes() == b"aaaa"
        assert not tree.exists("/src/a.txt")

    def test_download_and_upload(self, tree, tmp_path):
        progress = Progress()
        local = str(tmp_path / "a.txt")
        self.ops.download(tree, "/src/a.txt", local, progress)
        self.ops.upload(local, tree, "/up.txt", progress)
        assert tree.cat_file("/up.txt") == b"aaaa"
        assert progress.bytes_done >= 4


@pytest.fixture
def async_tree(tree):
    """``tree`` as an asynchronous filesystem, as s3fs, gcsfs or adlfs are."""
    return AsyncFileSystemWrapper(tree)


class TestAsyncFsspecOperations:
    ops = AsyncFsspecOperations(concurrency=2, delete_batch=2)

    def test_copy_folder_concurrently(self, tree, async_tree):
        progress = Recorder()
        self.ops.copy(async_tree, "/src", async_tree, "/dst", progress)
        assert tree.cat_file("/dst/sub/c.txt") == b"c"
        assert sorted(progress.names) == ["a.txt", "b.txt", "c.txt"]
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_copy_cancelled_in_a_batch(self, tree, async_tree, monkeypatch):
        ops = AsyncFsspecOperations(concurrency=1)
        progress = Progress()
        original = async_tree._cp_file

        async def cp_then_cancel(*args: Any, **kwargs: Any) -> None:
            await original(*args, **kwargs)
            progress.cancel()

        monkeypatch.setattr(async_tree, "_cp_file", cp_then_cancel)
        with pytest.raises(OperationCancelled):
            ops.copy(async_tree, "/src", async_tree, "/dst", progress)
        assert len(tree.find("/dst")) == 1

    def test_failure_raised(self, async_tree, monkeypatch):
        async def failing(*args: Any, **kwargs: Any) -> None:
            raise OSError("denied")

        monkeypatch.setattr(async_tree, "_cp_file", failing)
        with pytest.raises(OSError, match="denied"):
            self.ops.copy(async_tree, "/src", async_tree, "/dst", Progress())

    def test_copy_between_filesystems(self, async_tree, tmp_path):
        local = AsyncFileSystemWrapper(fsspec.filesystem("file"))
        progress = Progress()
        target = (tmp_path / "copy").as_posix()
        self.ops.copy(async_tree, "/src", local, target, progress)
        assert (tmp_path / "copy" / "sub" / "c.txt").read_bytes() == b"c"
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_move_between_filesystems(self, tree, async_tree, tmp_path):
        local = AsyncFileSystemWrapper(fsspec.filesystem("file"))
        progress = Progress()
        target = (tmp_path / "moved").as_posix()
        self.ops.move(async_tree, "/src", local, target, progress)
        assert (tmp_path / "moved" / "sub" / "c.txt").read_bytes() == b"c"
        assert not tree.exists("/src")
        assert (progress.files_done, progress.bytes_done) == (3, 7)
        self.ops.move(local, f"{target}/a.txt", async_tree, "/a.txt", Progress())
        assert tree.cat_file("/a.txt") == b"aaaa"
        assert not (tmp_path / "moved" / "a.txt").exists()

    def test_delete_folder_in_batches(self, tree, async_tree):
        progress = Progress()
        self.ops.delete(async_tree, "/src", progress)
        assert not tree.exists("/src")
        assert progress.files_done == 3

    def test_move_within_the_filesystem(self, tree, async_tree):
        self.ops.move(async_tree, "/src/a.txt", async_tree, "/a.txt", Progress())
        assert tree.cat_file("/a.txt") == b"aaaa"
        progress = Recorder()
        self.ops.move(async_tree, "/src", async_tree, "/moved", progress)
        assert tree.cat_file("/moved/sub/c.txt") == b"c"
        assert not tree.exists("/src")
        assert sorted(progress.names) == ["b.txt", "c.txt"]
        assert (progress.files_done, progress.bytes_done) == (2, 3)

    def test_download_upload_mkdir(self, tree, async_tree, tmp_path):
        progress = Progress()
        local = str(tmp_path / "b.txt")
        self.ops.download(async_tree, "/src/b.txt", local, progress)
        self.ops.upload(local, async_tree, "/up.txt", progress)
        assert tree.cat_file("/up.txt") == b"bb"
        assert progress.bytes_done >= 2
        self.ops.mkdir(async_tree, "/new")
        assert tree.isdir("/new")

    def test_other_filesystems_left_to_the_next(self, tree):
        with pytest.raises(FileSystemOperations.NotSupported):
            self.ops.copy(tree, "/src", tree, "/dst", Progress())


class TestAtomicMoveOperation:
    ops = AtomicMoveOperation()

    def test_moves_a_folder_with_one_mv(self, tree, monkeypatch):
        calls = []
        original = tree.mv

        def mv(*args: Any, **kwargs: Any) -> None:
            calls.append(args)
            original(*args, **kwargs)

        monkeypatch.setattr(tree, "mv", mv)
        self.ops.move(tree, "/src", tree, "/moved", Progress())
        assert calls == [("/src", "/moved")]
        assert tree.cat_file("/moved/sub/c.txt") == b"c"

    def test_local_folder_under_a_dir_filesystem(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.txt").write_bytes(b"a")
        fs = DirFileSystem(tmp_path.as_posix(), fsspec.filesystem("file"))
        self.ops.move(fs, "src", fs, "moved", Progress())
        assert (tmp_path / "moved" / "a.txt").read_bytes() == b"a"

    def test_everything_else_left_to_the_next(self, tree, tmp_path):
        local = fsspec.filesystem("file")
        for ops, args in [
            # Not one of its protocols.
            (AtomicMoveOperation(["file"]), (tree, "/src", tree, "/moved")),
            # Between filesystems.
            (self.ops, (tree, "/src", local, (tmp_path / "x").as_posix())),
        ]:
            with pytest.raises(FileSystemOperations.NotSupported):
                ops.move(*args, Progress())
        with pytest.raises(FileSystemOperations.NotSupported):
            self.ops.copy(tree, "/src", tree, "/copy", Progress())
        assert tree.exists("/src/a.txt")


def test_same_filesystem(memfs):
    # fsspec caches filesystems: the same arguments give the same storage.
    assert same_filesystem(memfs, fsspec.filesystem("memory"))
    assert same_filesystem(memfs, memfs)
    assert not same_filesystem(memfs, fsspec.filesystem("file"))


class TestOperationChain:
    def test_in_the_order_given(self, tree, async_tree):
        chain = OperationChain([AtomicMoveOperation(), FsspecOperations()])
        # Anything but a move within a filesystem: FsspecOperations.
        chain.copy(tree, "/src", tree, "/again", Progress())
        assert tree.exists("/again/a.txt")
        chain.move(tree, "/again", tree, "/moved", Progress())
        assert tree.cat_file("/moved/sub/c.txt") == b"c"

    def test_first_that_supports_it_wins(self, tree):
        calls = []

        class Trash(FileSystemOperations):
            """Deletes into /trash, on memory filesystems only."""

            def delete(self, fs, path, progress):
                if fs.protocol != "memory" and "memory" not in fs.protocol:
                    raise self.NotSupported
                calls.append(path)
                fs.mv(path, "/trash/" + path.rsplit("/", 1)[-1], recursive=True)

        chain = OperationChain([Trash(), FsspecOperations()])
        chain.delete(tree, "/src/a.txt", Progress())
        assert calls == ["/src/a.txt"]
        assert tree.exists("/trash/a.txt")
        # Not supported by Trash: the next one's.
        chain.copy(tree, "/src/b.txt", tree, "/b2.txt", Progress())
        assert tree.cat_file("/b2.txt") == b"bb"

    def test_no_defaults_added(self):
        chain = OperationChain([FileSystemOperations()])
        assert [type(o) for o in chain.operations] == [FileSystemOperations]
        with pytest.raises(ValueError, match="no operations objects"):
            OperationChain([])

    def test_unknown_operation(self):
        with pytest.raises(AttributeError):
            _ = OperationChain([FsspecOperations()]).rename

    def test_other_not_implemented_errors_are_errors(self, tree):
        """A NotImplementedError raised for another reason (e.g. by a library)
        is reported, not taken as "not supported" by the next object."""

        class Library(FileSystemOperations):
            def copy(self, fs, source, target_fs, target, progress):
                raise NotImplementedError("this filesystem cannot copy")

        chain = OperationChain([Library(), FsspecOperations()])
        with pytest.raises(NotImplementedError, match="cannot copy"):
            chain.copy(tree, "/src/a.txt", tree, "/a2.txt", Progress())
        assert not tree.exists("/a2.txt")

    def test_nobody_supports_it(self, tree):
        chain = OperationChain([FileSystemOperations(), FileSystemOperations()])
        with pytest.raises(FileSystemOperations.NotSupported, match="no operations"):
            chain.copy(tree, "/a", tree, "/b", Progress())


class TestJobRunner:
    def test_inline_without_a_loop(self):
        sent = []
        runner = JobRunner(lambda job: sent.append((job.state, job.result)))
        finished = []
        job = runner.submit(
            "test", "Testing", lambda p: {"done": [1]}, finish=finished.append
        )
        assert finished == [job]
        assert sent[0][0] == "queued"
        assert sent[-1] == ("done", {"done": [1]})
        assert runner.jobs == {}

    def test_failed_and_cancelled(self):
        runner = JobRunner(lambda job: None)

        def boom(progress):
            raise ValueError("no")

        failed = runner.submit("test", "Failing", boom)
        assert (failed.state, failed.error) == ("failed", "ValueError: no")

        def cancel_midway(progress):
            progress.cancel()
            progress.check()

        assert runner.submit("test", "Cancelled", cancel_midway).state == "cancelled"
        partial = runner.submit("test", "Partial", lambda p: {"cancelled": True})
        assert partial.state == "cancelled"

    def test_update_before_each_report(self, monkeypatch):
        monkeypatch.setattr(jobs, "REPORT_INTERVAL", 0)
        events = []
        runner = JobRunner(lambda job: events.append(("notify", job.state)))

        def work(progress):
            progress.advance(files=1)
            return {}

        runner.submit(
            "test",
            "Updating",
            work,
            update=lambda job: events.append(("update", job.state)),
        )
        assert ("update", "running") in events
        at = events.index(("update", "running"))
        assert events[at + 1] == ("notify", "running")  # the update comes first

    def test_failing_update_does_not_stop_the_job(self, monkeypatch):
        monkeypatch.setattr(jobs, "REPORT_INTERVAL", 0)
        runner = JobRunner(lambda job: None)

        def update(job):
            raise RuntimeError("broken")

        def work(progress):
            progress.advance(files=1)
            return {"ok": True}

        job = runner.submit("test", "Updating", work, update=update)
        assert (job.state, job.result) == ("done", {"ok": True})

    def test_in_a_worker_thread_with_a_loop(self):
        """In a kernel: the work runs in a worker thread, reports and finishing
        on the loop's (main) thread."""

        async def main() -> dict[str, Any]:
            done = asyncio.Event()
            seen: dict[str, Any] = {"notify_threads": set(), "states": []}

            def notify(job):
                seen["notify_threads"].add(threading.current_thread().name)
                seen["states"].append(job.state)
                if job.finished:
                    done.set()

            def work(progress):
                seen["work_thread"] = threading.current_thread().name
                progress.add_total(files=2)
                progress.advance(files=2)
                return {"ok": True}

            def finish(job):
                seen["finish_thread"] = threading.current_thread().name

            runner = JobRunner(notify)
            runner.submit("test", "Threaded", work, finish)
            await asyncio.wait_for(done.wait(), 5)
            return seen

        seen = asyncio.run(main())
        main_thread = threading.current_thread().name
        assert seen["work_thread"].startswith("jse-job")
        assert seen["finish_thread"] == main_thread
        assert seen["notify_threads"] == {main_thread}
        assert seen["states"][0] == "queued" and seen["states"][-1] == "done"
