"""Properties: a file's info, and the totals of the files and folders scanned."""

from __future__ import annotations

import datetime as dt
import os
from typing import TYPE_CHECKING, Any

import fsspec
import pytest

from jupyter_storage_explorer import StorageExplorer, _paths
from jupyter_storage_explorer._infos import mtime
from jupyter_storage_explorer._jobs.operation_chain import OperationChain
from jupyter_storage_explorer._jobs.progress import JobProgress
from jupyter_storage_explorer._jobs.properties import file_properties, scan
from jupyter_storage_explorer._jobs.runner import JobRunner

if TYPE_CHECKING:
    from pathlib import Path

    from jupyter_storage_explorer.filesystems.operation import Progress

DAY = 24 * 3600


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """data/a.csv (day 2), data/sub/b.csv (day 1), data/sub/deep/c.csv (day 3),
    data/empty/ and top.txt (day 4)."""
    files = {
        "data/a.csv": (b"aa", 2),
        "data/sub/b.csv": (b"b", 1),
        "data/sub/deep/c.csv": (b"ccc", 3),
        "top.txt": (b"tttt", 4),
    }
    for name, (data, day) in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (day * DAY, day * DAY))
    (tmp_path / "data" / "empty").mkdir()
    return tmp_path


def at(tree: Path, name: str) -> str:
    return _paths.norm(str(tree / name).replace("\\", "/"))


class TestScan:
    """scan(): ``measure`` (see test_operations.py) of each item selected."""

    fs = fsspec.filesystem("file")
    ops = OperationChain(StorageExplorer.default_operations())

    def scan(self, paths: list[str], progress: Progress | None = None) -> Any:
        return scan(self.ops, self.fs, paths, progress or JobProgress())

    def test_one_folder_what_it_holds(self, tree):
        result = self.scan([at(tree, "data")])
        assert {k: result[k] for k in ("files", "folders", "bytes", "errors")} == {
            "files": 3,
            "folders": 3,  # sub, sub/deep, empty: not data itself
            "bytes": 6,
            "errors": [],
        }
        assert result["oldest"] == {"mtime": DAY, "path": at(tree, "data/sub/b.csv")}
        assert result["newest"] == {
            "mtime": 3 * DAY,
            "path": at(tree, "data/sub/deep/c.csv"),
        }

    def test_items_and_what_their_folders_hold(self, tree):
        result = self.scan([at(tree, "data/sub"), at(tree, "top.txt")])
        # The folder selected counts, with the one in it.
        assert (result["files"], result["folders"], result["bytes"]) == (3, 2, 8)
        assert result["newest"]["path"] == at(tree, "top.txt")

    def test_progress(self, tree):
        progress = JobProgress()
        self.scan([at(tree, "data")], progress)
        assert (progress.files_done, progress.bytes_done) == (3, 6)

    def test_items_not_found_are_errors(self, tree):
        result = self.scan([at(tree, "top.txt"), at(tree, "gone")])
        assert result["files"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0].startswith(at(tree, "gone"))

    def test_cancelled_gives_the_counts_so_far(self, tree):
        def cancel_once_files_counted() -> None:
            if progress.files_done:
                progress.cancel()

        progress = JobProgress(on_change=cancel_once_files_counted)
        result = self.scan([at(tree, "top.txt"), at(tree, "data")], progress)
        assert result["cancelled"] is True
        assert result["files"] == 1  # top.txt; data not measured

    def test_no_modification_times(self, memfs, monkeypatch):
        memfs.pipe_file("/d/a", b"a")
        info = memfs.info

        def without_times(path: str, **kwargs: Any) -> dict[str, Any]:
            return {k: v for k, v in info(path, **kwargs).items() if k != "created"}

        monkeypatch.setattr(memfs, "info", without_times)
        result = scan(self.ops, memfs, ["/d/a"], JobProgress())
        assert (result["files"], result["oldest"], result["newest"]) == (1, None, None)


def test_mtime_whichever_key():
    when = dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    assert mtime({"mtime": 5}) == 5.0
    assert mtime({"LastModified": when}) == when.timestamp()
    assert mtime({"last_modified": "2025-01-02T00:00:00+00:00"}) == when.timestamp()
    assert mtime({"size": 1}) is None


def test_file_properties():
    when = dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    info = {
        "name": "bucket/a.csv",
        "size": 3,
        "type": "file",
        "LastModified": when,
        "ETag": '"x"',
    }
    assert file_properties(info, "s3://bucket/a.csv") == {
        "name": "a.csv",
        "path": "bucket/a.csv",
        "url": "s3://bucket/a.csv",
        "type": "file",
        "size": 3,
        "mtime": when.timestamp(),
        "info": {**info, "LastModified": when.isoformat()},  # as JSON values
    }


def test_job_ids_by_runner():
    runner = JobRunner(lambda job: None, prefix="scan")
    assert runner.submit("properties", "Counting", lambda progress: {}).id == "scan-1"
