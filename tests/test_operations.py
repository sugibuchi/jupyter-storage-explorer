"""operations.py and jobs.py: file operations with progress and cancellation, run as jobs."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import fsspec
import pytest

from jupyter_storage_explorer.jobs import JobRunner
from jupyter_storage_explorer.operations import (
    FileSystemOperations,
    FsspecOperations,
    OperationCancelled,
    OperationChain,
    Progress,
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


class TestFsspecOperations:
    ops = FsspecOperations()

    def test_measure(self, tree):
        assert self.ops.measure(tree, "/src") == (3, 7)
        assert self.ops.measure(tree, "/src/a.txt") == (1, 4)

    def test_copy_folder_file_by_file(self, tree):
        progress = Recorder()
        self.ops.copy(tree, "/src", "/dst", progress)
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
                self.ops.copy(tree, "/src", "/dst", progress)
        finally:
            del tree.cp_file
        assert len(tree.find("/dst")) == 1

    def test_copy_between_filesystems(self, tree, tmp_path):
        local = fsspec.filesystem("file")
        target = (tmp_path / "copy").as_posix()
        progress = Progress()
        self.ops.copy_between(tree, "/src", local, target, progress)
        assert (tmp_path / "copy" / "sub" / "c.txt").read_bytes() == b"c"
        assert (progress.files_done, progress.bytes_done) == (3, 7)

    def test_delete_folder_in_batches(self, tree, monkeypatch):
        monkeypatch.setattr(FsspecOperations, "DELETE_BATCH", 2)
        progress = Progress()
        self.ops.delete(tree, "/src", progress)
        assert not tree.exists("/src")
        assert progress.files_done == 3

    def test_move_and_mkdir(self, tree):
        self.ops.move(tree, "/src", "/moved", Progress())
        assert tree.cat_file("/moved/a.txt") == b"aaaa"
        self.ops.mkdir(tree, "/new")
        assert tree.isdir("/new")

    def test_download_and_upload(self, tree, tmp_path):
        progress = Progress()
        local = str(tmp_path / "a.txt")
        self.ops.download(tree, "/src/a.txt", local, progress)
        self.ops.upload(local, tree, "/up.txt", progress)
        assert tree.cat_file("/up.txt") == b"aaaa"
        assert progress.bytes_done >= 4


class TestOperationChain:
    def test_first_implementation_wins_and_fsspec_is_last(self, tree):
        calls = []

        class Trash(FileSystemOperations):
            """Deletes into /trash, on memory filesystems only."""

            def delete(self, fs, path, progress):
                if fs.protocol != "memory" and "memory" not in fs.protocol:
                    raise NotImplementedError
                calls.append(path)
                fs.mv(path, "/trash/" + path.rsplit("/", 1)[-1], recursive=True)

        chain = OperationChain([Trash()])
        assert isinstance(chain.operations[-1], FsspecOperations)
        chain.delete(tree, "/src/a.txt", Progress())
        assert calls == ["/src/a.txt"]
        assert tree.exists("/trash/a.txt")
        # Not implemented by Trash: fsspec's.
        chain.copy(tree, "/src/b.txt", "/b2.txt", Progress())
        assert tree.cat_file("/b2.txt") == b"bb"

    def test_unknown_operation(self):
        with pytest.raises(AttributeError):
            _ = OperationChain().rename


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
