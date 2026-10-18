"""StorageExplorer from Python: on_change(), query_result(), on_query_change()
and open_preview."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import make, path_of

from jupyter_storage_explorer import _paths


@pytest.fixture
def explorer(tmp_path):
    pl.DataFrame({"a": [3, 1, 2], "b": ["x", "y", "z"]}).write_parquet(
        tmp_path / "data.parquet"
    )
    pl.DataFrame({"a": [5, 4]}).write_parquet(tmp_path / "more.parquet")
    (tmp_path / "notes.txt").write_bytes(b"hello\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.txt").write_bytes(b"x")
    return make(str(tmp_path))


def selected(explorer, *names):
    """Select items as the frontend does: a change of the synced trait."""
    explorer._selected = [path_of(explorer, name) for name in names]


class TestOnChange:
    def test_folder_and_selection(self, explorer):
        calls = []
        explorer.on_change(
            lambda e: calls.append(
                (e.folder_url, [_paths.basename(u) for u in e.selected_urls])
            )
        )
        top = explorer.folder_url
        selected(explorer, "notes.txt")
        selected(explorer, "notes.txt", "sub")
        selected(explorer, "notes.txt", "sub")  # the same: not a change
        explorer._current_dir = path_of(explorer, "sub")
        assert calls == [
            (top, ["notes.txt"]),
            (top, ["notes.txt", "sub"]),
            # Showing a folder clears the selection: one change.
            (explorer.folder_url, []),
        ]
        assert explorer.folder_url.endswith("sub")

    def test_storage_switch_is_one_change(self, tmp_path, memfs):
        memfs.pipe_file("/m/a.txt", b"a")
        explorer = make(filesystems={"disk": str(tmp_path), "mem": memfs})
        calls = []
        explorer.on_change(lambda e: calls.append(e._filesystem))
        explorer._filesystem = "mem"
        assert calls == ["mem"]

    def test_removed_and_errors_do_not_stop_others(self, explorer):
        calls = []

        def failing(_):
            raise RuntimeError("boom")

        def counting(_):
            calls.append(1)

        explorer.on_change(counting)
        explorer.on_change(counting)  # once only
        # Without IPython's shell (here), errors are raised, after the
        # functions before them were called.
        explorer.on_change(failing)
        with pytest.raises(RuntimeError):
            selected(explorer, "notes.txt")
        explorer.on_change(failing, remove=True)
        explorer.on_change(counting, remove=True)
        selected(explorer, "sub")
        assert calls == [1]


class TestQueryResult:
    def query_rows(self, explorer, path, **settings):
        return explorer.request(
            {
                "type": "query_rows",
                "rid": 1,
                "path": path,
                "offset": 0,
                "window": 10,
                "settings": settings,
            }
        )

    def test_none_unless_a_table_is_shown(self, explorer):
        assert explorer.query_result() is None
        explorer.message({"type": "preview", "path": path_of(explorer, "notes.txt")})
        assert explorer.query_result() is None

    def test_follows_the_browser(self, explorer):
        path = path_of(explorer, "data.parquet")
        explorer.message({"type": "preview", "path": path})
        assert explorer.query_result().collect()["a"].to_list() == [3, 1, 2]
        self.query_rows(
            explorer, path, sort={"column": "a", "descending": False}, hidden=["b"]
        )
        assert explorer.query_result().collect().to_dict(as_series=False) == {
            "a": [1, 2, 3]
        }
        assert explorer.query_result(all_columns=True).collect().columns == ["a", "b"]
        explorer.message({"type": "preview", "path": path_of(explorer, "notes.txt")})
        assert explorer.query_result() is None

    def test_on_query_change(self, explorer):
        calls = []

        def record(e):
            result = e.query_result()
            calls.append(None if result is None else result.collect()["a"].to_list())

        explorer.on_query_change(record)
        data, more = (
            path_of(explorer, "data.parquet"),
            path_of(explorer, "more.parquet"),
        )
        explorer.message({"type": "preview", "path": data})  # not told while loading
        self.query_rows(explorer, data)  # the first page: no change
        self.query_rows(explorer, data, sort={"column": "a", "descending": True})
        self.query_rows(explorer, data, sort={"column": "a", "descending": True})
        explorer.request({"type": "query_reload", "rid": 2, "path": data})
        explorer.message({"type": "preview", "path": more})
        explorer._preview = {}  # closed by the frontend
        explorer._preview = {}
        assert calls == [[3, 1, 2], [3, 2, 1], [3, 2, 1], [5, 4], None]

        explorer.on_query_change(record, remove=True)
        explorer.message({"type": "preview", "path": data})
        assert len(calls) == 5


class TestOpenPreview:
    def test_open_and_kept_open_across_storages(self, tmp_path, memfs):
        memfs.pipe_file("/m/a.txt", b"a")
        explorer = make(filesystems={"disk": str(tmp_path), "mem": memfs})
        assert explorer._preview == {}
        explorer = make(
            filesystems={"disk": str(tmp_path), "mem": memfs}, open_preview=True
        )
        assert explorer._preview == {"empty": True}
        explorer._filesystem = "mem"
        assert explorer._preview == {"empty": True}
        explorer._open_preview("/m/a.txt")
        explorer._filesystem = "disk"
        assert explorer._preview == {"empty": True}
        explorer._preview = {}  # closed
        explorer._filesystem = "mem"
        assert explorer._preview == {}
