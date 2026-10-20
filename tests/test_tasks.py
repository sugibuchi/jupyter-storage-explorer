"""_jobs/tasks.py and _jobs/incoming.py, without a widget."""

from __future__ import annotations

import dataclasses
import os

import fsspec
import pytest

from jupyter_storage_explorer._jobs import tasks as tasks_module
from jupyter_storage_explorer._jobs.incoming import IncomingFiles
from jupyter_storage_explorer._jobs.operation_chain import OperationChain
from jupyter_storage_explorer._jobs.progress import JobProgress
from jupyter_storage_explorer._jobs.tasks import FileTasks, Task
from jupyter_storage_explorer.filesystems import (
    FsspecOperations,
    LocalMapper,
    MapperChain,
    default_mappers,
)
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
)


@pytest.fixture
def tasks(memfs) -> FileTasks:
    memfs.pipe({"/d/a.txt": b"a", "/d/b.txt": b"b", "/e/b.txt": b"old"})
    return FileTasks(memfs, "/", OperationChain([FsspecOperations()]))


def run(task: Task) -> dict:
    assert isinstance(task, Task)
    return task.work(JobProgress())


class TestFileTasks:
    def test_move_records_what_changed(self, tasks):
        task = tasks.move(["/d/a.txt"], "/e")
        assert task.title == "Moving a.txt to e"
        assert run(task) == {"moved": ["a.txt"], "skipped": [], "errors": []}
        assert task.moved == [("/d/a.txt", "/e/a.txt")]
        assert task.changed == {"/d", "/e"}

    def test_conflicts_asked_first(self, tasks):
        assert tasks.move(["/d/b.txt"], "/e") == {"conflicts": ["b.txt"]}
        assert tasks.paste([(tasks.fs, "/d/b.txt")], "/e") == {"conflicts": ["b.txt"]}

    def test_cut_within_the_filesystem_is_a_move(self, tasks):
        task = tasks.paste([(tasks.fs, "/d/a.txt")], "/e", cut=True)
        assert task.title == "Moving a.txt into e"
        assert run(task) == {"moved": ["a.txt"], "skipped": [], "errors": []}
        assert task.moved == [("/d/a.txt", "/e/a.txt")]
        assert task.changed == {"/d", "/e"}

    def test_cut_from_another_filesystem(self, tasks, tmp_path):
        (tmp_path / "f.txt").write_bytes(b"f")
        local = fsspec.filesystem("file")
        source = local._strip_protocol(str(tmp_path / "f.txt"))
        task = tasks.paste([(local, source)], "/e", cut=True)
        assert run(task)["moved"] == ["f.txt"]
        assert tasks.fs.cat_file("/e/f.txt") == b"f"
        assert not (tmp_path / "f.txt").exists()
        # The source is on another filesystem: recorded apart, for the explorer.
        assert task.moved == [] and task.moved_away == [(local, source)]
        assert task.changed == {"/e"}

    def test_cut_over_an_existing_file(self, tasks):
        task = tasks.paste([(tasks.fs, "/d/b.txt")], "/e", "overwrite", cut=True)
        run(task)
        assert tasks.fs.cat_file("/e/b.txt") == b"b"
        assert not tasks.fs.exists("/d/b.txt")

    def test_cut_folders_need_unsafe_mode(self, tasks):
        tasks.fs.pipe_file("/d/sub/x.txt", b"x")
        reply = run(tasks.paste([(tasks.fs, "/d/sub")], "/e", cut=True))
        assert reply["errors"] == [
            "sub: folders are not moved (turn on unsafe mode first)"
        ]

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


def test_operations_are_told_if_within_one_filesystem(tmp_path):
    """Two local filesystems with other options: one, as the mappers tell."""
    _operations_told(tmp_path, MapperChain(default_mappers()), [True])


def test_operations_told_by_the_explorers_mappers(tmp_path):
    """Operations get the explorer's mappers' answer, not the defaults'."""

    class ByOption(LocalMapper):
        """Local filesystems apart by an option, unlike the default mapper."""

        def to_location(self, fs, path):
            location = super().to_location(fs, path)
            return dataclasses.replace(location, hostname=f"auto-{fs.auto_mkdir}")

    _operations_told(tmp_path, MapperChain([ByOption(), *default_mappers()]), [False])


def _operations_told(tmp_path, mappers, same):
    told = []

    class Told(FileSystemOperations):
        def copy(self, source_fs, source, target_fs, target, progress, *, same):
            told.append(same)
            raise self.NotSupported

    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "e").mkdir()
    source = fsspec.filesystem("file")
    target = fsspec.filesystem("file", auto_mkdir=True)
    assert source != target
    root = target._strip_protocol(str(tmp_path))
    tasks = FileTasks(
        target, root, OperationChain([Told(), FsspecOperations()]), mappers=mappers
    )
    run(tasks.paste([(source, f"{root}/a.txt")], f"{root}/e"))
    assert told == same
    assert (tmp_path / "e" / "a.txt").read_bytes() == b"a"


def test_directly_in(tmp_path):
    folder = str(tmp_path)
    assert tasks_module._directly_in(os.path.join(folder, "a.csv"), folder)
    assert not tasks_module._directly_in(os.path.join(folder, "sub", "a.csv"), folder)
    assert not tasks_module._directly_in(str(tmp_path.parent / "a.csv"), folder)


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows'")
def test_download_name_with_another_drive_refused(memfs, tmp_path):
    """On Windows, "X:name" joined to a folder of another drive is a path of
    its own (drive X's current folder): never written."""
    drive = "Z:" if not str(tmp_path).upper().startswith("Z:") else "Y:"
    memfs.pipe_file(f"/d/{drive}evil.py", b"x")
    tasks = FileTasks(memfs, "/", OperationChain([FsspecOperations()]))
    reply = run(tasks.download([f"/d/{drive}evil.py"], str(tmp_path)))
    assert reply["copied"] == []
    assert "not a file name of this system" in reply["errors"][0]
