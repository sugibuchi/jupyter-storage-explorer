"""StorageExplorer's jobs, and following what they change."""

from __future__ import annotations

from typing import Any

import pytest
from explorers import Explorer, entries, make, storage, without_ids

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer import jobs as following
from jupyter_storage_explorer._jobs import runner as jobs
from jupyter_storage_explorer.fs_operations import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
)
from jupyter_storage_explorer.fs_operations.base import FileSystemOperations


class Watch(FileSystemOperations):
    """Records what the explorer shows as each item of a job starts, then
    leaves the item to the default operations."""

    def __init__(self) -> None:
        self.explorer: Explorer | None = None
        self.seen: list[dict[str, Any]] = []

    def _look(self) -> None:
        explorer = self.explorer
        self.seen.append(
            {
                # In the storage's order: the browser sorts.
                "list": sorted(e["name"] for e in entries(explorer)),
                "selected": [_paths.basename(p) for p in explorer._selected],
                "tree": [d["name"] for d in explorer._tree.get("/d", [])],
            }
        )
        raise self.NotSupported

    def delete(self, fs, path, progress):
        self._look()

    def copy(self, source_fs, source, target_fs, target, progress):
        self._look()

    def move(self, source_fs, source, target_fs, target, progress):
        self._look()


class TestFollowingJobs:
    """The list, selection and tree change as a job goes, not only once it has ended."""

    @pytest.fixture
    def explorer(self, memfs, monkeypatch) -> tuple[Explorer, Watch]:
        monkeypatch.setattr(jobs, "REPORT_INTERVAL", 0)
        monkeypatch.setattr(following, "_FOLLOW_INTERVAL", 0)
        monkeypatch.setattr(following, "_RELIST_INTERVAL", 0)
        memfs.pipe({f"/d/f{i}.txt": b"x" for i in range(1, 4)})
        memfs.pipe(
            {"/src/n1.txt": b"", "/src/n2.txt": b"", "/d/a/x": b"", "/d/b/x": b""}
        )
        watch = Watch()
        explorer = make("/", fs=memfs, operations=[watch])
        watch.explorer = explorer
        explorer._current_dir = "/d"
        return explorer, watch

    def test_deleted_files_leave_as_they_go(self, explorer):
        explorer, watch = explorer
        explorer._selected = ["/d/f1.txt", "/d/f2.txt", "/d/f3.txt", "/d/a"]
        explorer.request(
            {
                "type": "delete",
                "rid": 1,
                "paths": ["/d/f1.txt", "/d/f2.txt", "/d/f3.txt"],
            }
        )
        assert [s["list"] for s in watch.seen] == [
            ["a", "b", "f1.txt", "f2.txt", "f3.txt"],
            ["a", "b", "f2.txt", "f3.txt"],
            ["a", "b", "f3.txt"],
        ]
        assert watch.seen[-1]["selected"] == ["f3.txt", "a"]

    def test_deleted_folders_leave_the_tree(self, explorer):
        explorer, watch = explorer
        explorer.request(
            {"type": "delete", "rid": 1, "paths": ["/d/a", "/d/b"], "unsafe": True}
        )
        assert [s["tree"] for s in watch.seen] == [["a", "b"], ["b"]]

    def test_pasted_files_appear_as_they_go(self, explorer):
        explorer, watch = explorer
        explorer._selected = ["/d/f1.txt"]
        explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": storage(explorer),
                "files": [{"path": p} for p in ("/src/n1.txt", "/src/n2.txt")],
                "dest": "/d",
            }
        )
        before = ["a", "b", "f1.txt", "f2.txt", "f3.txt"]
        assert [s["list"] for s in watch.seen] == [before, [*before, "n1.txt"]]
        assert watch.seen[-1]["selected"] == ["f1.txt"]  # kept
        assert "n2.txt" in [e["name"] for e in entries(explorer)]  # at the end

    def test_moved_files_leave_and_follow(self, explorer):
        explorer, watch = explorer
        explorer.request(
            {
                "type": "move",
                "rid": 1,
                "paths": ["/d/f1.txt", "/d/f2.txt"],
                "dest": "/d/a",
            }
        )
        assert [s["list"] for s in watch.seen] == [
            ["a", "b", "f1.txt", "f2.txt", "f3.txt"],
            ["a", "b", "f2.txt", "f3.txt"],
        ]

    def test_at_most_every_follow_interval(self, explorer, monkeypatch):
        explorer, watch = explorer
        monkeypatch.setattr(following, "_FOLLOW_INTERVAL", 3600)
        explorer.request(
            {
                "type": "delete",
                "rid": 1,
                "paths": ["/d/f1.txt", "/d/f2.txt", "/d/f3.txt"],
            }
        )
        # Shown once when it started (nothing done yet), then only at its end.
        assert all(len(s["list"]) == 5 for s in watch.seen)
        assert [e["name"] for e in entries(explorer)] == ["a", "b"]

    def test_not_after_switching_storage(self, memfs, monkeypatch, tmp_path):
        monkeypatch.setattr(jobs, "REPORT_INTERVAL", 0)
        monkeypatch.setattr(following, "_FOLLOW_INTERVAL", 0)
        memfs.pipe({"/d/f1.txt": b"", "/d/f2.txt": b""})
        (tmp_path / "f1.txt").write_text("")
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        task = explorer._tasks().delete(["/d/f1.txt", "/d/f2.txt"])
        explorer._filesystem = "local"  # the user switches while it is planned
        explorer._start(task)  # no error, the local list untouched
        assert [e["name"] for e in entries(explorer)] == ["f1.txt"]


class TestJobs:
    """Move, delete, paste and downloads run as jobs (see runner.py); without a
    kernel loop, at once."""

    def test_job_messages(self, mem_explorer):
        mem_explorer.message(
            {"type": "move", "rid": 1, "paths": ["/data/a.csv"], "dest": "/other"}
        )
        reply = mem_explorer.sent[-1][0]
        assert reply == {"type": "reply", "rid": 1, "job": reply["job"]}
        states = [
            c["state"] for c, _ in mem_explorer.sent if c.get("id") == reply["job"]
        ]
        assert states[0] == "queued" and states[-1] == "done"
        final = mem_explorer.job(reply["job"])
        assert final["title"] == "Moving a.csv to other"
        assert final["result"] == {"moved": ["a.csv"], "skipped": [], "errors": []}
        assert (final["files_total"], final["files_done"]) == (1, 1)

    def test_nothing_to_do_needs_no_job(self, mem_explorer):
        reply = mem_explorer.request(
            {"type": "delete", "rid": 1, "paths": ["/data/table"]}
        )
        assert "job" not in reply
        assert reply["deleted"] == []

    def test_default_operations(self, memfs):
        kinds = [type(o) for o in make("/", fs=memfs)._operations.operations]
        assert kinds == [AtomicMoveOperation, AsyncFsspecOperations, FsspecOperations]
        # Those given come first, then the defaults.
        explorer = make("/", fs=memfs, operations=[FileSystemOperations()])
        assert [type(o) for o in explorer._operations.operations] == [
            FileSystemOperations,
            *kinds,
        ]

    def test_operations_of_your_own(self, memfs):
        """An operations object doing deletions its own way, fsspec the rest."""

        class Trash(FileSystemOperations):
            def delete(self, fs, path, progress):
                fs.mv(path, "/trash/" + path.rsplit("/", 1)[-1])

        memfs.pipe({"/d/a.txt": b"a", "/d/b.txt": b"b"})
        explorer = make("/d", fs=memfs, operations=[Trash()])
        explorer.request({"type": "delete", "rid": 1, "paths": ["/d/a.txt"]})
        assert memfs.cat_file("/trash/a.txt") == b"a"
        explorer.request(
            {"type": "move", "rid": 1, "paths": ["/d/b.txt"], "dest": "/trash"}
        )
        assert memfs.exists("/trash/b.txt")  # moved by AtomicMoveOperation

    def test_cancelled_midway(self, memfs):
        """Cancelled after the first file: that one is pasted, the job says so."""

        class CancelAfterOne(FileSystemOperations):
            def copy(self, fs, source, target_fs, target, progress):
                fs.cp_file(source, target)
                progress.cancel()

        memfs.pipe({"/d/a.txt": b"a", "/d/b.txt": b"b", "/d/c.txt": b"c"})
        explorer = make(
            "/d",
            fs=memfs,
            operations=[CancelAfterOne()],
        )
        explorer.message(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": storage(explorer),
                "files": [{"path": f"/d/{n}"} for n in ("a.txt", "b.txt", "c.txt")],
                "dest": "/out",
            }
        )
        final = explorer.job(explorer.sent[-1][0]["job"])
        assert final["state"] == "cancelled"
        assert final["result"] == {
            "pasted": ["a.txt"],
            "skipped": [],
            "errors": [],
            "cancelled": True,
        }
        assert memfs.find("/out") == ["/out/a.txt"]

    def test_cancelled_inside_an_item(self, memfs):
        """Cancelled while copying a folder: it is named as left incomplete."""

        class CancelInside(FileSystemOperations):
            def copy(self, fs, source, target_fs, target, progress):
                fs.makedirs(target, exist_ok=True)
                progress.cancel()
                progress.check()  # between two files of the folder

        memfs.pipe({"/d/big/a.txt": b"a", "/d/big/b.txt": b"b"})
        explorer = make(
            "/d",
            fs=memfs,
            operations=[CancelInside()],
        )
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": storage(explorer),
                "files": [{"path": "/d/big"}],
                "dest": "/out",
                "unsafe": True,
            }
        )
        assert without_ids(reply) == {
            "pasted": [],
            "skipped": [],
            "errors": [],
            "cancelled": True,
            "incomplete": "big",
        }

    def test_cancel_unknown_job(self, mem_explorer):
        mem_explorer.message({"type": "job_cancel", "id": "job-99"})  # no error
