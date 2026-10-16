"""StorageExplorer's bookmarks, and its states kept in a file."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import Explorer, make, path_of

from jupyter_storage_explorer.query import QuerySettings, fetch_rows
from jupyter_storage_explorer.states import ExplorerStates


class TestBookmarks:
    def bookmarks(self, explorer: Explorer) -> list[tuple[str, str, str]]:
        reply = explorer.request({"type": "bookmarks", "rid": 1})
        return [(b["filesystem"], b["path"], b["label"]) for b in reply["bookmarks"]]

    def test_add_the_folder_shown(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        reply = mem_explorer.request(
            {"type": "bookmark_add", "rid": 1, "path": "/data"}
        )
        [bookmark] = reply["bookmarks"]
        assert bookmark == {
            "filesystem": "default",
            "path": "/data",
            "url": "memory:///data",
            "label": "[default] /data",
        }
        assert mem_explorer._states.bookmarks[0].url == "memory:///data"

    @pytest.mark.parametrize("path", ["/data/a.csv", "/missing"])
    def test_only_folders(self, mem_explorer, path):
        reply = mem_explorer.request({"type": "bookmark_add", "rid": 1, "path": path})
        assert "is not a folder" in reply["error"]

    def test_open_in_the_storage_shown(self, mem_explorer):
        mem_explorer._states.add_bookmark("default", "/data")
        assert mem_explorer.request(
            {
                "type": "bookmark_open",
                "rid": 1,
                "filesystem": "default",
                "path": "/data",
            }
        ) == {"type": "reply", "rid": 1}
        assert mem_explorer._current_dir == "/data"

    def test_open_in_another_storage(self, memfs, tmp_path):
        memfs.pipe_file("/m/sub/x.txt", b"")
        explorer = make(filesystems={"local": str(tmp_path), "mem": memfs})
        explorer.request(
            {"type": "bookmark_open", "rid": 1, "filesystem": "mem", "path": "/m/sub"}
        )
        assert (explorer._filesystem, explorer._current_dir) == ("mem", "/m/sub")

    def test_open_a_folder_gone(self, mem_explorer):
        reply = mem_explorer.request(
            {
                "type": "bookmark_open",
                "rid": 1,
                "filesystem": "default",
                "path": "/gone",
            }
        )
        assert reply["error"] == "/gone no longer exists"
        assert mem_explorer._current_dir == "/"

    def test_only_those_of_its_storages(self, memfs):
        memfs.pipe({"/top/sub/a.txt": b"", "/secret/b.txt": b""})
        states = ExplorerStates()
        for filesystem, path in [
            ("mem", "/top/sub"),
            ("mem", "/top"),
            ("mem", "/secret"),  # outside its top folder
            ("other", "/top"),  # a storage it does not have
        ]:
            states.add_bookmark(filesystem, path)
        explorer = make(filesystems={"mem": "memory:///top"}, states=states)
        assert self.bookmarks(explorer) == [
            ("mem", "/top", "[mem] /top"),
            ("mem", "/top/sub", "[mem] /top/sub"),
        ]
        reply = explorer.request(
            {"type": "bookmark_open", "rid": 1, "filesystem": "mem", "path": "/secret"}
        )
        assert "not in this explorer's storages" in reply["error"]

    def test_remove(self, mem_explorer):
        mem_explorer._states.add_bookmark("default", "/data")
        reply = mem_explorer.request(
            {
                "type": "bookmark_remove",
                "rid": 1,
                "filesystem": "default",
                "path": "/data",
            }
        )
        assert reply["bookmarks"] == []

    def test_shared_by_explorers_with_the_same_states(self, memfs):
        states = ExplorerStates()
        first, second = (
            make("/", fs=memfs, states=states),
            make("/", fs=memfs, states=states),
        )
        memfs.mkdir("/data")
        first.request({"type": "bookmark_add", "rid": 1, "path": "/data"})
        assert self.bookmarks(second) == [("default", "/data", "[default] /data")]

    def test_alphabetical_order_of_storage_then_path(self, memfs, tmp_path):
        states = ExplorerStates()
        for filesystem, path in [
            ("b", "/m/z"),
            ("B", "/m/A"),
            ("a", "/m/b"),
            ("b", "/m/a"),
        ]:
            states.add_bookmark(filesystem, path)
        explorer = make(filesystems={"a": memfs, "b": memfs, "B": memfs}, states=states)
        assert [label for _, _, label in self.bookmarks(explorer)] == [
            "[a] /m/b",
            "[B] /m/A",
            "[b] /m/a",
            "[b] /m/z",
        ]


class TestStatesFile:
    def test_read_again_when_an_explorer_is_created(self, memfs, tmp_path):
        path = tmp_path / "states.json"
        states = ExplorerStates(path)
        ExplorerStates(path).add_bookmark("default", "/data")  # e.g. another kernel
        memfs.mkdir("/data")
        explorer = make("/", fs=memfs, states=states)
        assert [b.path for b in explorer._states.bookmarks] == ["/data"]

    def test_given_as_a_path(self, memfs, tmp_path):
        path = tmp_path / "states.json"
        memfs.mkdir("/data")
        first = make("/", fs=memfs, states=str(path))
        second = make("/", fs=memfs, states=path)
        assert first._states is second._states
        first.request({"type": "bookmark_add", "rid": 1, "path": "/data"})
        assert ExplorerStates(path).bookmarks[0].path == "/data"

    def test_unreadable_file_given_as_a_path(self, memfs, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{typo")
        explorer = make("/", fs=memfs, states=path)
        assert explorer._error.startswith("Bookmarks and queries not read again")

    def test_unreadable_file_reported(self, memfs, tmp_path):
        path = tmp_path / "states.json"
        states = ExplorerStates(path)
        path.write_text("{broken")
        explorer = make("/", fs=memfs, states=states)
        assert explorer._error.startswith("Bookmarks and queries not read again")

    def test_query_reopens_in_the_mode_chosen(self, tmp_path):
        # More rows than max_live_rows (5000), so "auto" queries live.
        pl.DataFrame({"a": range(6000)}).write_parquet(tmp_path / "big.parquet")
        explorer = make(str(tmp_path))
        path = path_of(explorer, "big.parquet")
        explorer.message({"type": "preview", "path": path})
        assert explorer._queries[path].mode == "live"
        explorer.request(
            {
                "type": "query_mode",
                "rid": 1,
                "path": path,
                "mode": "memory",
                "settings": {},
            }
        )
        explorer.message({"type": "preview", "path": path})  # opened again
        assert explorer._queries[path].mode == "memory"
        explorer._states.remember_query(explorer._url(path), QuerySettings(), "live")
        explorer.message({"type": "preview", "path": path})
        assert explorer._queries[path].mode == "live"

    def test_query_with_fetch_rows_given(self, tmp_path):
        fetched = []

        def fetch(lf, offset, length):
            fetched.append((offset, length))
            return fetch_rows(lf, offset, length)

        # More rows than max_live_rows (5000), so "auto" queries live.
        pl.DataFrame({"a": range(6000)}).write_parquet(tmp_path / "big.parquet")
        explorer = make(str(tmp_path), fetch_rows=fetch)
        path = path_of(explorer, "big.parquet")
        explorer.message({"type": "preview", "path": path})
        reply = explorer.request(
            {"type": "query_rows", "rid": 1, "path": path, "offset": 5998, "window": 5}
        )
        assert reply["rows"] == [[5998], [5999]]
        assert fetched == [(5998, 6)]
