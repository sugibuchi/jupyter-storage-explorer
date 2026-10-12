"""file_tasks.py and incoming.py, without a widget."""

from __future__ import annotations

import os

import pytest

from jupyter_storage_explorer.file_tasks import FileTasks, Task
from jupyter_storage_explorer.incoming import IncomingFiles
from jupyter_storage_explorer.operations import (
    FsspecOperations,
    OperationChain,
    Progress,
)


@pytest.fixture
def tasks(memfs) -> FileTasks:
    memfs.pipe({"/d/a.txt": b"a", "/d/b.txt": b"b", "/e/b.txt": b"old"})
    return FileTasks(memfs, "/", OperationChain([FsspecOperations()]))


def run(task: Task) -> dict:
    assert isinstance(task, Task)
    return task.work(Progress())


class TestFileTasks:
    def test_move_records_what_changed(self, tasks):
        task = tasks.move(["/d/a.txt"], "/e")
        assert task.title == "Moving a.txt to e"
        assert run(task) == {"moved": ["a.txt"], "skipped": [], "errors": []}
        assert task.moved == [("/d/a.txt", "/e/a.txt")]
        assert task.changed == {"/d", "/e"}

    def test_conflicts_asked_first(self, tasks):
        assert tasks.move(["/d/b.txt"], "/e") == {"conflicts": ["b.txt"]}
        assert tasks.paste([{"path": "/d/b.txt"}], "/e", same_filesystem=True) == {
            "conflicts": ["b.txt"]
        }

    def test_delete_records_removed(self, tasks):
        task = tasks.delete(["/d/a.txt"])
        assert run(task) == {"deleted": ["a.txt"], "errors": []}
        assert task.removed == ["/d/a.txt"]
        assert task.changed == {"/d"}

    def test_upload_local_files(self, tasks, tmp_path):
        (tmp_path / "f.txt").write_bytes(b"f")
        task = tasks.upload([str(tmp_path / "f.txt")], "/e")
        assert task.kind == "upload"
        assert run(task)["copied"] == ["f.txt"]
        assert tasks.fs.cat_file("/e/f.txt") == b"f"

    def test_upload_file_cleans_up(self, tasks, tmp_path):
        local = tmp_path / "received"
        local.write_bytes(b"data")
        task = tasks.upload_file(str(local), "/e/new.txt")
        assert run(task) == {"copied": ["new.txt"], "errors": []}
        task.cleanup()
        assert not local.exists()
        assert tasks.fs.cat_file("/e/new.txt") == b"data"


class TestIncomingFiles:
    def test_pieces_gathered(self, memfs):
        incoming = IncomingFiles(max_bytes=None)
        incoming.add("u", b"hello ", "/x.txt", memfs)
        received = incoming.add("u", b"world", "/x.txt", memfs)
        assert received.size == 11
        done = incoming.pop("u")
        with open(done.path, "rb") as f:
            assert f.read() == b"hello world"
        os.unlink(done.path)

    def test_too_large_and_discarded(self, memfs):
        incoming = IncomingFiles(max_bytes=3)
        received = incoming.add("u", b"12", "/x", memfs)
        with pytest.raises(ValueError, match="over 3 B"):
            incoming.add("u", b"34", "/x", memfs)
        incoming.discard("u")
        assert not os.path.exists(received.path)
