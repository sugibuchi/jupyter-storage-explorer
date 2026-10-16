"""StorageExplorer's Python side, driven by the messages its frontend sends."""

from __future__ import annotations

import json
from typing import Any

import fsspec
import polars as pl
import pytest
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import StorageExplorer, _paths, jobs, storage_explorer
from jupyter_storage_explorer.filesystems import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
)
from jupyter_storage_explorer.incoming import format_size
from jupyter_storage_explorer.operations import FileSystemOperations
from jupyter_storage_explorer.query import QuerySettings, fetch_rows
from jupyter_storage_explorer.states import ExplorerStates


class Explorer(StorageExplorer):
    """Keeps what would be sent to the frontend in ``sent``, as (content, buffers)."""

    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        self.__dict__.setdefault("sent", []).append((content, buffers))

    def message(self, content: dict[str, Any], buffers: Any = None) -> None:
        """Send a message as the frontend does."""
        self._on_custom_msg(self, content, buffers)

    def request(self, content: dict[str, Any], buffers: Any = None) -> dict[str, Any]:
        """Send a message as the frontend does; the last message sent back.

        For a request that started a job ({"job": id}), its result instead:
        without a kernel loop, jobs run at once (see jobs.py), so the job has
        ended by then.
        """
        self.message(content, buffers)
        reply = self.sent[-1][0]
        if "job" in reply:
            return {
                **self.job(reply["job"])["result"],
                "type": "reply",
                "rid": reply.get("rid"),
            }
        return reply

    def job(self, job_id: str) -> dict[str, Any]:
        """The last message about job ``job_id``."""
        return [
            c for c, _ in self.sent if c.get("type") == "job" and c["id"] == job_id
        ][-1]


def make(*args: Any, **kwargs: Any) -> Explorer:
    kwargs.setdefault("states", ExplorerStates())
    return Explorer(*args, **kwargs)


@pytest.fixture
def mem_explorer(memfs) -> Explorer:
    memfs.pipe_file("/data/a.csv", b"x,y\n1,2\n")
    memfs.pipe_file("/data/notes.md", b"# Notes\n")
    memfs.pipe_file("/data/table/_delta_log/0.json", b"{}")
    memfs.pipe_file("/other/b.txt", b"b")
    return make("/", fs=memfs)


@pytest.fixture
def local(tmp_path) -> Explorer:
    """An explorer of a local folder, as polars reads local paths."""
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(tmp_path / "data.parquet")
    (tmp_path / "notes.txt").write_bytes(b"hello\n")
    return make(str(tmp_path))


def entries(explorer: Explorer) -> list[dict[str, Any]]:
    """The items of ``_listing`` as the frontend decodes them (listedEntries)."""
    listing = explorer._listing
    no_url = set(listing["no_url"])
    return [
        {
            "name": name,
            "path": listing["paths"][i]
            if listing["paths"] is not None
            else _paths.join(listing["dir"], name),
            "type": "directory" if listing["is_dir"][i] else "file",
            "size": listing["sizes"][i],
            "mtime": listing["mtimes"][i],
            "format": listing["formats"][listing["format"][i]],
            "no_url": i in no_url,
        }
        for i, name in enumerate(listing["names"])
    ]


def path_of(explorer: Explorer, name: str) -> str:
    return next(e["path"] for e in entries(explorer) if e["name"] == name)


class TestListing:
    def test_entries_and_tree(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        by_name = {e["name"]: e for e in entries(mem_explorer)}
        assert by_name["a.csv"]["format"] == "csv"
        assert by_name["a.csv"]["path"] == "/data/a.csv"
        assert by_name["a.csv"]["size"] == 8
        assert by_name["notes.md"]["format"] == "markdown"
        assert by_name["table"]["type"] == "directory"
        assert by_name["table"]["format"] == ""  # folders are not detected in the list
        assert not any(e["no_url"] for e in by_name.values())
        assert [d["name"] for d in mem_explorer._tree["/"]] == ["data", "other"]
        assert mem_explorer.folder_url == "memory:///data"

    def test_listing_is_compact(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        listing = mem_explorer._listing
        assert listing["dir"] == "/data"
        assert listing["paths"] is None  # each path is dir + "/" + name
        # Each format name once, and none ("") first.
        assert listing["formats"][0] == ""
        assert sorted(listing["formats"]) == ["", "csv", "markdown"]
        assert all(isinstance(t, int) for t in listing["mtimes"] if t is not None)
        assert "url" not in listing and "urls" not in listing

    def test_creation_times_for_tooltips(self, mem_explorer, tmp_path):
        # The memory filesystem lists files with "created"; folders without.
        mem_explorer._current_dir = "/data"
        listing = mem_explorer._listing
        ctimes = dict(zip(listing["names"], listing["ctimes"], strict=True))
        assert isinstance(ctimes["a.csv"], int)
        assert ctimes["table"] is None
        # Local files: fsspec's "created" (st_ctime).
        (tmp_path / "x.txt").write_bytes(b"x")
        local = Explorer(str(tmp_path))
        assert local._listing["ctimes"] == [int((tmp_path / "x.txt").stat().st_ctime)]

    def test_urls_on_request(self, mem_explorer):
        reply = mem_explorer.request(
            {"type": "urls", "rid": 1, "paths": ["/data/a.csv", "/data"]}
        )
        assert reply == {
            "type": "reply",
            "rid": 1,
            "urls": ["memory:///data/a.csv", "memory:///data"],
        }

    def test_items_without_url(self, memfs):
        class NoCsvUrls(Explorer):
            def _url(self, path):
                return None if path.endswith((".csv", "/sub")) else super()._url(path)

        memfs.pipe_file("/d/a.csv", b"x")
        memfs.pipe_file("/d/b.txt", b"x")
        memfs.pipe_file("/d/sub/c.txt", b"x")
        explorer = NoCsvUrls("/d", fs=memfs, states=ExplorerStates())
        assert {e["name"] for e in entries(explorer) if e["no_url"]} == {"a.csv", "sub"}
        assert explorer._tree["/d"] == [
            {"name": "sub", "path": "/d/sub", "no_url": True}
        ]

    def test_paths_listed_when_not_joined(self, mem_explorer, monkeypatch):
        # A filesystem whose listing names items other than "dir/name".
        listed = mem_explorer._ls("/data")
        monkeypatch.setattr(
            mem_explorer,
            "_ls",
            lambda path: [
                {**i, "name": "/elsewhere/" + i["name"].rsplit("/", 1)[1]}
                for i in listed
            ],
        )
        mem_explorer._current_dir = "/data"
        assert mem_explorer._listing["paths"] is not None
        assert path_of(mem_explorer, "a.csv") == "/elsewhere/a.csv"

    def test_large_folders_are_paged_by_the_kernel(self, memfs):
        memfs.pipe({"/data/a.csv": b"x", "/data/b.csv": b"xy", "/data/c.txt": b"z"})
        explorer = make("/", fs=memfs, max_browser_items=2)
        explorer._current_dir = "/data"
        listing = explorer._listing
        assert listing == {
            "dir": "/data",
            "query": True,
            "total": 3,
            "version": listing["version"],
        }
        reply = explorer.request(
            {
                "type": "list",
                "rid": 7,
                "dir": "/data",
                "version": listing["version"],
                "text": "csv",
                "sort": "size",
                "asc": False,
                "page": 0,
                "page_size": 100,
            }
        )
        assert reply["rid"] == 7
        assert reply["listing"]["names"] == ["b.csv", "a.csv"]
        assert (reply["matching"], reply["total"], reply["page"]) == (2, 3, 0)

    def test_stale_page_requests(self, memfs):
        memfs.pipe({"/data/a.csv": b"x", "/data/b.csv": b"x", "/data/c.txt": b"x"})
        explorer = make("/", fs=memfs, max_browser_items=2)
        explorer._current_dir = "/data"
        version = explorer._listing["version"]
        explorer._refresh()  # listed again: a new version
        for dir_, ver in (("/data", version), ("/", explorer._listing["version"])):
            reply = explorer.request(
                {"type": "list", "rid": 1, "dir": dir_, "version": ver}
            )
            assert reply["stale"] is True

    def test_saving_changes_the_version_of_a_large_listing(self, memfs):
        memfs.pipe({"/data/a.md": b"x", "/data/b.md": b"x", "/data/c.md": b"x"})
        explorer = make("/", fs=memfs, max_browser_items=2)
        explorer._current_dir = "/data"
        version = explorer._listing["version"]
        explorer.request(
            {
                "type": "jupyterlab_save",
                "rid": 1,
                "filesystem": explorer._filesystem,
                "path": "/data/a.md",
                "content": "longer",
                "format": "text",
            }
        )
        assert explorer._listing["version"] != version
        page = explorer.request(
            {
                "type": "list",
                "rid": 1,
                "dir": "/data",
                "version": explorer._listing["version"],
                "text": "a.md",
            }
        )
        assert page["listing"]["sizes"] == [6]

    def test_no_limit(self, memfs):
        memfs.pipe({f"/data/{i}.txt": b"x" for i in range(5)})
        explorer = make("/", fs=memfs, max_browser_items=None)
        explorer._current_dir = "/data"
        assert len(entries(explorer)) == 5

    def test_current_directory_format(self, mem_explorer):
        mem_explorer._current_dir = "/data/table"
        assert mem_explorer._current_format == "delta"

    def test_selection(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        mem_explorer._selected = ["/data/a.csv"]
        assert mem_explorer.selected_urls == ["memory:///data/a.csv"]
        assert mem_explorer._selected_format["format"] == "csv"
        mem_explorer._selected = ["/data/a.csv", "/data/notes.md"]
        assert mem_explorer._selected_format == {}

    def test_listing_error(self, mem_explorer):
        mem_explorer._current_dir = "/missing"
        assert mem_explorer._error.startswith("Cannot list /missing")
        assert entries(mem_explorer) == []

    def test_expand(self, mem_explorer):
        mem_explorer.message({"type": "expand", "path": "/data"})
        assert [d["name"] for d in mem_explorer._tree["/data"]] == ["table"]


class TestFilesystems:
    def test_switching_remembers_folders(self, memfs, tmp_path):
        memfs.pipe_file("/m/x.txt", b"")
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        assert explorer._filesystem_names == ["mem", "local"]
        explorer._current_dir = "/m"
        explorer._filesystem = "local"
        assert explorer._root == explorer._current_dir
        explorer._filesystem = "mem"
        assert explorer._current_dir == "/m"

    def test_remembered_folder_that_cannot_be_checked(
        self, memfs, tmp_path, monkeypatch
    ):
        memfs.pipe_file("/m/x.txt", b"")
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        explorer._current_dir = "/m"
        explorer._filesystem = "local"

        def broken(path):
            raise RuntimeError("storage unreachable")

        monkeypatch.setattr(memfs, "isdir", broken)
        explorer._filesystem = "mem"  # no error: back at the top instead
        assert explorer._current_dir == explorer._root == "/"

    def test_restore_view(self, memfs, tmp_path):
        """The launcher's tab reopens where it was: the storage shown at its
        folder, the other's folder remembered."""
        memfs.pipe_file("/m/sub/x.txt", b"")
        (tmp_path / "data").mkdir()
        local_folder = (tmp_path / "data").as_posix()
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        explorer._restore_view("local", {"mem": "/m/sub", "local": local_folder})
        assert (explorer._filesystem, explorer._current_dir) == ("local", local_folder)
        explorer._filesystem = "mem"
        assert explorer._current_dir == "/m/sub"

    def test_restore_view_in_the_storage_shown(self, memfs, tmp_path):
        memfs.pipe_file("/m/sub/x.txt", b"")
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        explorer._restore_view("mem", {"mem": "/m/sub"})
        assert (explorer._filesystem, explorer._current_dir) == ("mem", "/m/sub")

    @pytest.mark.parametrize(
        ("filesystem", "folders"),
        [
            ("gone", {"gone": "/x"}),  # a storage no longer offered
            ("mem", {"mem": "/m/missing"}),  # a folder that is gone
            ("mem", {"mem": 3}),  # not a folder
            ("mem", "not a dict"),
        ],
    )
    def test_restore_view_ignores_what_cannot_be_used(self, memfs, filesystem, folders):
        explorer = make(filesystems={"mem": memfs})
        explorer._restore_view(filesystem, folders)
        assert (explorer._filesystem, explorer._current_dir) == ("mem", "/")

    def test_restore_view_stays_in_the_top_folder(self, memfs):
        memfs.pipe({"/top/a.txt": b"", "/secret/b.txt": b""})
        explorer = make(filesystems={"mem": "memory:///top"})
        for folder in ("/secret", "/top/../secret"):
            explorer._restore_view("mem", {"mem": folder})
            assert explorer._current_dir == "/top"

    def test_unknown_filesystem(self, memfs):
        explorer = make(filesystems={"mem": memfs})
        with pytest.raises(Exception, match="unknown filesystem"):
            explorer._filesystem = "nope"

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"filesystems": {}}, ValueError),
            ({"filesystems": {"a": "."}, "path": "."}, TypeError),
            ({"formats": [], "format_options": {}}, TypeError),
            ({"format_options": {"typo": 1}}, ValueError),
        ],
    )
    def test_invalid_arguments(self, kwargs, error):
        with pytest.raises(error):
            make(**kwargs)

    def test_storage_options_with_fs(self, memfs):
        with pytest.raises(TypeError, match="storage options"):
            make(fs=memfs, anon=True)


class TestPreview:
    def test_text(self, local):
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        assert local._preview["format"] == "text"
        [section] = local._preview["sections"]
        assert (section["kind"], section["text"]) == ("text", "hello\n")

    def test_queryable_data_opens_the_data_browser(self, local):
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path})
        assert local._preview["format"] == "parquet"
        assert [c["name"] for c in local._preview["query"]["columns"]] == ["a"]
        reply = local.request(
            {"type": "query_rows", "rid": 7, "path": path, "offset": 0, "window": 2}
        )
        assert reply["type"] == "reply"
        assert reply["rid"] == 7
        assert (reply["rows"], reply["more"]) == ([[1], [2]], True)

    def test_preview_as_another_format(self, mem_explorer):
        mem_explorer._open_preview("/data/a.csv", "text")
        assert mem_explorer._preview["format"] == "text"
        mem_explorer._open_preview("/data/a.csv", "image")
        assert "cannot be previewed as image" in mem_explorer._preview["error"]

    def test_query_after_close(self, local):
        reply = local.request({"type": "query_rows", "rid": 1, "path": "gone"})
        assert reply["error"].startswith("the data is no longer open")


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


def test_menu_info(mem_explorer):
    reply = mem_explorer.request({"type": "menu_info", "rid": 1, "path": "/data/a.csv"})
    assert reply["formats"] == ["csv", "text"]
    assert [r["library"] for r in reply["recipes"]] == ["polars", "pandas", "pyspark"]
    folder = mem_explorer.request(
        {"type": "menu_info", "rid": 1, "path": "/data/table"}
    )
    assert folder["formats"] == ["delta"]


def test_download(mem_explorer):
    mem_explorer.message({"type": "download", "paths": ["/data/a.csv", "/data/table"]})
    (file_reply, buffers), (folder_reply, _) = mem_explorer.sent[-2:]
    assert (file_reply["name"], buffers) == ("a.csv", [b"x,y\n1,2\n"])
    assert "folders cannot be downloaded" in folder_reply["error"]


class TestDownloadToJupyterLab:
    def copy(self, explorer, paths, if_exists="ask"):
        """The kernel's reply, without "type" and "rid"."""
        reply = explorer.request(
            {
                "type": "download_to_jupyterlab",
                "rid": 1,
                "paths": paths,
                "if_exists": if_exists,
            }
        )
        return {k: v for k, v in reply.items() if k not in ("type", "rid")}

    def test_default_is_the_folder_launched_in(self, memfs, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        memfs.pipe_file("/a.csv", b"a")
        explorer = make("/", fs=memfs)
        assert explorer._download_to_jupyterlab_path == str(tmp_path)
        # Still there after the working directory changes.
        monkeypatch.chdir(tmp_path.parent)
        assert self.copy(explorer, ["/a.csv"]) == {
            "copied": ["a.csv"],
            "skipped": [],
            "errors": [],
        }
        assert (tmp_path / "a.csv").read_bytes() == b"a"

    def test_home_folder(self, memfs, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
        (tmp_path / "Downloads").mkdir()
        explorer = make("/", fs=memfs, download_to_jupyterlab_path="~/Downloads")
        assert explorer._download_to_jupyterlab_path == str(tmp_path / "Downloads")

    @pytest.mark.parametrize(
        ("if_exists", "content"), [("skip", b"mine"), ("overwrite", b"a")]
    )
    def test_conflicts(self, memfs, tmp_path, if_exists, content):
        memfs.pipe_file("/a.csv", b"a")
        (tmp_path / "a.csv").write_bytes(b"mine")
        explorer = make("/", fs=memfs, download_to_jupyterlab_path=str(tmp_path))
        assert self.copy(explorer, ["/a.csv"]) == {"conflicts": ["a.csv"]}
        self.copy(explorer, ["/a.csv"], if_exists)
        assert (tmp_path / "a.csv").read_bytes() == content

    def test_missing_folder(self, memfs, tmp_path):
        memfs.pipe_file("/a.csv", b"a")
        explorer = make(
            "/", fs=memfs, download_to_jupyterlab_path=str(tmp_path / "missing")
        )
        assert "folder not found" in self.copy(explorer, ["/a.csv"])["errors"][0]


def without_ids(reply):
    return {k: v for k, v in reply.items() if k not in ("type", "rid")}


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
        monkeypatch.setattr(storage_explorer, "_FOLLOW_INTERVAL", 0)
        monkeypatch.setattr(storage_explorer, "_RELIST_INTERVAL", 0)
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
                "filesystem": "default",
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
        monkeypatch.setattr(storage_explorer, "_FOLLOW_INTERVAL", 3600)
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
        monkeypatch.setattr(storage_explorer, "_FOLLOW_INTERVAL", 0)
        memfs.pipe({"/d/f1.txt": b"", "/d/f2.txt": b""})
        (tmp_path / "f1.txt").write_text("")
        explorer = make(filesystems={"mem": memfs, "local": str(tmp_path)})
        task = explorer._tasks().delete(["/d/f1.txt", "/d/f2.txt"])
        explorer._filesystem = "local"  # the user switches while it is planned
        explorer._start(task)  # no error, the local list untouched
        assert [e["name"] for e in entries(explorer)] == ["f1.txt"]


class TestDelete:
    def delete(self, explorer, paths):
        return without_ids(
            explorer.request({"type": "delete", "rid": 1, "paths": paths})
        )

    def test_files(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        reply = self.delete(mem_explorer, ["/data/a.csv", "/data/notes.md"])
        assert reply == {"deleted": ["a.csv", "notes.md"], "errors": []}
        assert not mem_explorer._fs.exists("/data/a.csv")
        # The list shows the folder without them.
        assert [e["name"] for e in entries(mem_explorer)] == ["table"]

    def test_folders_are_not_deleted(self, mem_explorer):
        reply = self.delete(mem_explorer, ["/data/table"])
        assert reply == {
            "deleted": [],
            "errors": ["table: folders are not deleted (turn on unsafe mode first)"],
        }
        assert mem_explorer._fs.exists("/data/table/_delta_log/0.json")

    def test_closes_the_preview_of_a_deleted_file(self, mem_explorer):
        mem_explorer._open_preview("/data/notes.md")
        assert mem_explorer._preview["path"] == "/data/notes.md"
        self.delete(mem_explorer, ["/data/notes.md"])
        assert mem_explorer._preview == {}

    def test_storage_error_is_reported(self, mem_explorer, monkeypatch):
        def broken(path):
            raise RuntimeError("storage unreachable")

        monkeypatch.setattr(mem_explorer._fs, "isdir", broken)
        reply = self.delete(mem_explorer, ["/data/a.csv"])
        assert reply == {"errors": ["RuntimeError: storage unreachable"]}
        monkeypatch.undo()
        assert mem_explorer._fs.exists("/data/a.csv")

    def test_missing_file(self, mem_explorer):
        reply = self.delete(mem_explorer, ["/data/gone.csv"])
        assert reply["deleted"] == []
        assert reply["errors"][0].startswith("gone.csv:")


class TestPaste:
    def paste(self, explorer, files, dest, *, source=None, if_exists="ask"):
        """Paste ``files`` (paths of ``source``, by default ``explorer``) into ``dest``."""
        source = source or explorer
        return without_ids(
            explorer.request(
                {
                    "type": "paste",
                    "rid": 1,
                    "explorer": source._explorer_id,
                    "filesystem": source._filesystem,
                    "files": [{"path": p, "url": source._url(p)} for p in files],
                    "dest": dest,
                    "if_exists": if_exists,
                }
            )
        )

    def test_within_the_filesystem(self, mem_explorer):
        mem_explorer._current_dir = "/other"
        reply = self.paste(mem_explorer, ["/data/a.csv", "/data/table"], "/other")
        assert reply == {
            "pasted": ["a.csv"],
            "skipped": [],
            "errors": ["table: folders are not pasted (turn on unsafe mode first)"],
        }
        assert mem_explorer._fs.cat_file("/other/a.csv") == b"x,y\n1,2\n"
        assert mem_explorer._fs.exists("/data/a.csv")  # copied, not moved
        assert "a.csv" in [e["name"] for e in entries(mem_explorer)]

    @pytest.mark.parametrize(
        ("if_exists", "content"), [("skip", b"b"), ("overwrite", b"new")]
    )
    def test_conflicts(self, mem_explorer, if_exists, content):
        mem_explorer._fs.pipe_file("/data/b.txt", b"new")
        assert self.paste(mem_explorer, ["/data/b.txt"], "/other") == {
            "conflicts": ["b.txt"]
        }
        self.paste(mem_explorer, ["/data/b.txt"], "/other", if_exists=if_exists)
        assert mem_explorer._fs.cat_file("/other/b.txt") == content

    def test_not_into_its_own_folder(self, mem_explorer):
        reply = self.paste(mem_explorer, ["/other/b.txt"], "/other")
        assert reply["errors"] == ["b.txt: already in that folder"]

    def test_from_another_explorer(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/a.csv"], local._root, source=mem_explorer)
        assert reply["pasted"] == ["a.csv"]
        assert (tmp_path / "a.csv").read_bytes() == b"x,y\n1,2\n"
        assert "a.csv" in [e["name"] for e in entries(local)]

    def test_from_an_explorer_in_this_kernel_by_its_filesystem(self, memfs, tmp_path):
        """A DirFileSystem's URLs do not say where it starts: an explorer of
        this kernel lends its filesystem; from another kernel, it fails."""
        memfs.pipe_file("/base/x.txt", b"x")
        source = make(fs=DirFileSystem("/base", memfs))
        local = make(str(tmp_path))
        path = path_of(source, "x.txt")
        assert self.paste(local, [path], local._root, source=source)["pasted"] == [
            "x.txt"
        ]
        assert (tmp_path / "x.txt").read_bytes() == b"x"
        source._explorer_id = "in-another-kernel"
        reply = self.paste(local, [path], local._root, source=source)
        assert "unknown" in reply["errors"][0]

    def test_by_url_from_another_kernel(self, mem_explorer, tmp_path):
        mem_explorer._explorer_id = "in-another-kernel"
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/a.csv"], local._root, source=mem_explorer)
        assert reply["pasted"] == ["a.csv"]
        assert (tmp_path / "a.csv").read_bytes() == b"x,y\n1,2\n"

    def test_folder_by_url_is_not_pasted(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/table"], local._root, source=mem_explorer)
        assert reply["errors"] == [
            "table: folders are not pasted (turn on unsafe mode first)"
        ]
        assert list(tmp_path.iterdir()) == []

    def test_unreadable_url(self, tmp_path):
        local = make(str(tmp_path))
        reply = local.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": "elsewhere",
                "filesystem": "default",
                "files": [{"path": "/x.csv", "url": "memory:///missing/x.csv"}],
                "dest": local._root,
            }
        )
        assert reply["pasted"] == []
        assert reply["errors"][0].startswith("x.csv:")
        assert list(tmp_path.iterdir()) == []


class TestCut:
    """ "Cut" then "Paste": a move, within a storage or to another."""

    def paste(self, explorer, files, dest, *, source, **content):
        return without_ids(
            explorer.request(
                {
                    "type": "paste",
                    "rid": 1,
                    "explorer": source._explorer_id,
                    "filesystem": source._filesystem,
                    "files": [{"path": p, "url": source._url(p)} for p in files],
                    "dest": dest,
                    "cut": True,
                    **content,
                }
            )
        )

    def test_between_explorers(self, mem_explorer, tmp_path):
        mem_explorer._current_dir = "/data"
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/a.csv"], local._root, source=mem_explorer)
        assert reply == {"moved": ["a.csv"], "skipped": [], "errors": []}
        assert (tmp_path / "a.csv").read_bytes() == b"x,y\n1,2\n"
        assert not mem_explorer._fs.exists("/data/a.csv")
        assert "a.csv" in [e["name"] for e in entries(local)]
        # The source explorer follows once its frontend is told (a page-wide event).
        assert "a.csv" in [e["name"] for e in entries(mem_explorer)]
        mem_explorer.message(
            {"type": "changed", "filesystem": "default", "paths": ["/data/a.csv"]}
        )
        assert "a.csv" not in [e["name"] for e in entries(mem_explorer)]

    def test_within_an_explorer(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        reply = self.paste(mem_explorer, ["/data/a.csv"], "/other", source=mem_explorer)
        assert reply["moved"] == ["a.csv"]
        assert mem_explorer._fs.exists("/other/a.csv")
        assert "a.csv" not in [e["name"] for e in entries(mem_explorer)]

    def test_between_the_storages_of_an_explorer(self, memfs, tmp_path):
        memfs.pipe_file("/m/a.txt", b"a")
        explorer = make(filesystems={"mem": "memory:///m", "local": str(tmp_path)})
        files = [{"path": "/m/a.txt", "url": "memory:///m/a.txt"}]
        explorer._filesystem = "local"
        reply = without_ids(
            explorer.request(
                {
                    "type": "paste",
                    "rid": 1,
                    "explorer": explorer._explorer_id,
                    "filesystem": "mem",
                    "files": files,
                    "dest": explorer._root,
                    "cut": True,
                }
            )
        )
        assert reply["moved"] == ["a.txt"]
        assert (tmp_path / "a.txt").read_bytes() == b"a"
        assert "a.txt" in [e["name"] for e in entries(explorer)]
        explorer._filesystem = "mem"
        assert entries(explorer) == []

    def test_the_top_folder_is_not_moved(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(local, ["/"], local._root, source=mem_explorer, unsafe=True)
        assert reply["errors"] == ["/: the top folder is not moved"]
        assert mem_explorer._fs.exists("/data/a.csv")

    def test_folders(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(
            local, ["/data/table"], local._root, source=mem_explorer, unsafe=True
        )
        assert reply["moved"] == ["table"]
        assert (tmp_path / "table" / "_delta_log" / "0.json").read_bytes() == b"{}"
        assert not mem_explorer._fs.exists("/data/table")


class TestFolderOperations:
    """Moving, deleting and pasting folders: only in unsafe mode ("unsafe")."""

    @pytest.fixture
    def explorer(self, memfs):
        memfs.pipe(
            {
                "/data/sub/x.txt": b"x",
                "/data/sub/deep/y.txt": b"y",
                "/data/a.csv": b"a",
                "/other/keep.txt": b"k",
            }
        )
        return make("/", fs=memfs)

    def request(self, widget, kind, /, **content):
        """``widget``'s reply to a ``kind`` request (``content`` may have its own "explorer")."""
        return without_ids(widget.request({"type": kind, "rid": 1, **content}))

    def test_move(self, explorer):
        explorer._current_dir = "/data/sub/deep"
        reply = self.request(
            explorer, "move", paths=["/data/sub"], dest="/other", unsafe=True
        )
        assert reply == {"moved": ["sub"], "skipped": [], "errors": []}
        assert sorted(explorer._fs.find("/other")) == [
            "/other/keep.txt",
            "/other/sub/deep/y.txt",
            "/other/sub/x.txt",
        ]
        assert not explorer._fs.exists("/data/sub")
        # The list follows the folder it showed to where it was moved.
        assert explorer._current_dir == "/other/sub/deep"

    @pytest.mark.parametrize(
        ("paths", "dest", "error"),
        [
            (
                ["/data/sub"],
                "/data/sub/deep",
                "sub: a folder cannot be moved into itself",
            ),
            (["/"], "/other", "/: the top folder is not moved"),
        ],
    )
    def test_move_refused(self, explorer, paths, dest, error):
        reply = self.request(explorer, "move", paths=paths, dest=dest, unsafe=True)
        assert reply["errors"] == [error]
        assert explorer._fs.exists("/data/sub/x.txt")

    def test_move_onto_an_existing_folder_is_refused(self, explorer):
        explorer._fs.pipe_file("/other/sub/old.txt", b"o")
        reply = self.request(
            explorer, "move", paths=["/data/sub"], dest="/other", unsafe=True
        )
        assert reply["errors"] == ["sub: already exists in that folder"]
        assert explorer._fs.exists("/other/sub/old.txt")
        assert explorer._fs.exists("/data/sub/x.txt")

    def test_delete(self, explorer):
        explorer._current_dir = "/data/sub/deep"
        explorer._open_preview("/data/sub/x.txt")
        reply = self.request(explorer, "delete", paths=["/data/sub"], unsafe=True)
        assert reply == {"deleted": ["sub"], "errors": []}
        assert explorer._fs.find("/data") == ["/data/a.csv"]
        assert explorer._preview == {}
        # The list shows the deleted folder's parent.
        assert explorer._current_dir == "/data"
        assert not any(k.startswith("/data/sub") for k in explorer._tree)

    def test_delete_the_top_folder_is_refused(self, explorer):
        reply = self.request(explorer, "delete", paths=["/"], unsafe=True)
        assert reply == {"deleted": [], "errors": ["/: the top folder is not deleted"]}

    def test_paste_within_the_filesystem(self, explorer):
        files = [{"path": "/data/sub", "url": explorer._url("/data/sub")}]
        content = {
            "explorer": explorer._explorer_id,
            "filesystem": explorer._filesystem,
            "files": files,
            "dest": "/other",
        }
        reply = self.request(explorer, "paste", unsafe=True, **content)
        assert reply == {"pasted": ["sub"], "skipped": [], "errors": []}
        assert explorer._fs.cat_file("/other/sub/deep/y.txt") == b"y"
        assert explorer._fs.exists("/data/sub/x.txt")  # copied, not moved
        into_itself = self.request(
            explorer, "paste", unsafe=True, **{**content, "dest": "/data/sub/deep"}
        )
        assert into_itself["errors"] == ["sub: a folder cannot be pasted into itself"]

    def test_paste_from_another_explorer_by_url(self, explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.request(
            local,
            "paste",
            explorer=explorer._explorer_id,
            filesystem=explorer._filesystem,
            files=[{"path": "/data/sub", "url": explorer._url("/data/sub")}],
            dest=local._root,
            unsafe=True,
        )
        assert reply == {"pasted": ["sub"], "skipped": [], "errors": []}
        assert (tmp_path / "sub" / "deep" / "y.txt").read_bytes() == b"y"
        assert (tmp_path / "sub" / "x.txt").read_bytes() == b"x"

    @pytest.mark.parametrize(
        ("type", "content"),
        [
            ("move", {"paths": ["/data/sub"], "dest": "/other"}),
            ("delete", {"paths": ["/data/sub"]}),
        ],
    )
    def test_locked(self, explorer, type, content):
        reply = self.request(explorer, type, **content)  # no "unsafe"
        assert "turn on unsafe mode first" in reply["errors"][0]
        assert explorer._fs.exists("/data/sub/x.txt")


class TestCreateFolder:
    def create(self, explorer, dest, name):
        return without_ids(
            explorer.request(
                {"type": "create_folder", "rid": 1, "dest": dest, "name": name}
            )
        )

    def test_in_memory(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        assert self.create(mem_explorer, "/data", "new") == {
            "created": "new",
            "hidden": False,
        }
        assert mem_explorer._fs.isdir("/data/new")
        assert "new" in [e["name"] for e in entries(mem_explorer)]
        assert "new" in [d["name"] for d in mem_explorer._tree["/data"]]

    def test_on_a_local_disk(self, tmp_path):
        explorer = make(str(tmp_path))
        reply = self.create(explorer, explorer._root, "new folder")
        assert reply == {"created": "new folder", "hidden": False}
        assert (tmp_path / "new folder").is_dir()

    @pytest.mark.parametrize(
        ("name", "error"),
        [
            ("", "enter a name"),
            ("   ", "enter a name"),
            (" x", "no spaces at the start or the end"),
            ("..", "'..' is not a name"),
            ("a/b", "a name, without / or \\"),
            ("a\\b", "a name, without / or \\"),
            ("a\tb", "no control characters"),
            ("x" * 256, "at most 255 characters"),
        ],
    )
    def test_invalid_names(self, mem_explorer, name, error):
        assert self.create(mem_explorer, "/data", name) == {"error": error}

    def test_existing(self, mem_explorer):
        for name in ("a.csv", "table"):  # a file, a folder
            reply = self.create(mem_explorer, "/data", name)
            assert reply == {"error": f"{name} already exists"}

    def test_storage_without_empty_folders(self, mem_explorer, monkeypatch):
        # Like S3 or Google Cloud Storage: creating a folder leaves nothing to see.
        monkeypatch.setattr(mem_explorer._fs, "makedirs", lambda path, exist_ok: None)
        assert self.create(mem_explorer, "/data", "new") == {
            "created": "new",
            "hidden": True,
        }


class TestQueryTab:
    """ "Query data" in a new tab: a DataExplorer of the same query."""

    def test_opened_with_the_remembered_settings_and_closed(self, local):
        path = path_of(local, "data.parquet")
        url = local._url(path)
        local._states.remember_query(url, QuerySettings(sort="a", descending=True))
        reply = local.request({"type": "query_tab", "rid": 1, "path": path})
        assert reply["title"] == "data.parquet" and reply["url"] == url
        tab = local._query_tabs[reply["model_id"]]
        # Labelled with the file's format, as in the preview, not its library.
        assert (tab.height, tab.library) == ("fill", "Parquet")
        assert tab.settings.to_dict()["sort"] == {"column": "a", "descending": True}
        # Its settings are remembered by URL, as the preview's.
        tab._data.handle(
            {
                "type": "query_save",
                "rid": 2,
                "settings": {"sort": None, "hidden": ["a"]},
            }
        )
        assert local._states.query(url).settings.to_dict()["hidden"] == ["a"]
        local.message({"type": "query_tab_closed", "model_id": reply["model_id"]})
        assert reply["model_id"] not in local._query_tabs

    def test_refused_for_what_cannot_be_queried(self, local):
        reply = local.request(
            {"type": "query_tab", "rid": 1, "path": path_of(local, "notes.txt")}
        )
        assert reply["error"] == "notes.txt cannot be queried"
        assert not local._query_tabs


class TestOpenInJupyterLab:
    """The requests of the launcher's drive ("Open in JupyterLab"), through the explorer."""

    def get(self, explorer: Explorer, path: str, **options: Any) -> dict[str, Any]:
        return explorer.request(
            {
                "type": "jupyterlab_get",
                "rid": 1,
                "filesystem": explorer._filesystem,
                "path": path,
                **options,
            }
        )

    def save(self, explorer: Explorer, path: str, content: Any, **options: Any):
        return explorer.request(
            {
                "type": "jupyterlab_save",
                "rid": 2,
                "filesystem": explorer._filesystem,
                "path": path,
                "content": content,
                "format": "text",
                **options,
            }
        )

    def test_get_and_save(self, mem_explorer, memfs):
        model = self.get(mem_explorer, "/data/notes.md", format="text")["model"]
        assert model["content"] == "# Notes\n"
        saved = self.save(mem_explorer, "/data/notes.md", "# Changed\n")["model"]
        assert memfs.cat_file("/data/notes.md") == b"# Changed\n"
        assert saved["content"] is None and saved["hash"] != model["hash"]
        # The list shows the new size.
        mem_explorer._current_dir = "/data"
        assert {e["name"]: e["size"] for e in entries(mem_explorer)}["notes.md"] == 10

    def test_by_storage_name_while_another_is_shown(self, memfs):
        memfs.pipe_file("/a/f.txt", b"a")
        memfs.pipe_file("/b/g.txt", b"b")
        explorer = make(filesystems={"A": "memory:///a", "B": "memory:///b"})
        explorer._filesystem = "B"
        reply = explorer.request(
            {
                "type": "jupyterlab_save",
                "rid": 1,
                "filesystem": "A",
                "path": "/a/f.txt",
                "content": "new",
                "format": "text",
            }
        )
        assert "model" in reply
        assert memfs.cat_file("/a/f.txt") == b"new"

    def test_preview_of_the_file_follows(self, mem_explorer):
        mem_explorer._open_preview("/data/notes.md", "markdown")
        self.save(mem_explorer, "/data/notes.md", "# Changed\n")
        assert "Changed" in json.dumps(mem_explorer._preview)

    def test_refused(self, mem_explorer):
        assert "error" in self.get(mem_explorer, "/data")  # a folder
        assert "error" in self.get(mem_explorer, "/data/missing.txt")
        assert "error" in self.get(mem_explorer, "/data/../other/b.txt")
        other = mem_explorer.request(
            {
                "type": "jupyterlab_get",
                "rid": 1,
                "filesystem": "nope",
                "path": "/data/a.csv",
            }
        )
        assert other["error"] == "not a file of this explorer's storages"

    def test_text_formats(self, mem_explorer):
        # Opened in JupyterLab's text editor even when it does not know the
        # file type; data files are not (Parquet, Excel), nor are formats
        # JupyterLab knows itself (CSV, JSON).
        assert {"text", "markdown"} <= set(mem_explorer._text_formats)
        assert not {"parquet", "excel", "delta", "image", "csv"} & set(
            mem_explorer._text_formats
        )

    def test_too_large(self, mem_explorer, memfs, monkeypatch):
        monkeypatch.setattr(storage_explorer._jupyterlab_files, "MAX_BYTES", 3)
        assert "too large" in self.get(mem_explorer, "/data/a.csv")["error"]


class TestRename:
    """ "Rename": a move within the item's folder; folders only in unsafe mode."""

    @pytest.fixture
    def explorer(self, memfs):
        memfs.pipe(
            {"/data/sub/deep/y.txt": b"y", "/data/a.csv": b"a", "/data/b.csv": b"b"}
        )
        return make("/", fs=memfs)

    def rename(self, explorer, path, name, unsafe=False):
        return without_ids(
            explorer.request(
                {
                    "type": "rename",
                    "rid": 1,
                    "path": path,
                    "name": name,
                    "unsafe": unsafe,
                }
            )
        )

    def test_a_file(self, explorer):
        explorer._current_dir = "/data"
        explorer._selected = ["/data/a.csv"]
        assert self.rename(explorer, "/data/a.csv", "c.csv") == {
            "renamed": ["c.csv"],
            "errors": [],
        }
        assert explorer._fs.cat_file("/data/c.csv") == b"a"
        assert not explorer._fs.exists("/data/a.csv")
        assert {e["name"] for e in entries(explorer)} == {"sub", "b.csv", "c.csv"}
        assert explorer._selected == []

    def test_a_folder_in_unsafe_mode(self, explorer):
        explorer._current_dir = "/data/sub/deep"
        reply = self.rename(explorer, "/data/sub", "renamed", unsafe=True)
        assert reply == {"renamed": ["renamed"], "errors": []}
        assert explorer._fs.cat_file("/data/renamed/deep/y.txt") == b"y"
        # The list follows the folder it showed, and the tree the new name.
        assert explorer._current_dir == "/data/renamed/deep"
        assert "renamed" in [d["name"] for d in explorer._tree["/data"]]
        assert "sub" not in [d["name"] for d in explorer._tree["/data"]]

    @pytest.mark.parametrize(
        ("path", "name", "unsafe", "error"),
        [
            ("/data/sub", "other", False, "folders are renamed only in unsafe mode"),
            ("/", "other", True, "the top folder is not renamed"),
            ("/data/a.csv", "b.csv", False, "b.csv already exists"),
            ("/data/a.csv", "sub", False, "sub already exists"),
            ("/data/a.csv", "a.csv", False, "that is its name already"),
            ("/data/a.csv", "x/y.csv", False, "a name, without / or \\"),
            ("/data/a.csv", "..", False, "'..' is not a name"),
        ],
    )
    def test_refused(self, explorer, path, name, unsafe, error):
        assert self.rename(explorer, path, name, unsafe) == {"error": error}
        assert explorer._fs.cat_file("/data/a.csv") == b"a"
        assert explorer._fs.exists("/data/sub/deep/y.txt")


class TestProperties:
    """The "properties" request (the scan itself: test_properties.py)."""

    def test_a_file_at_once(self, mem_explorer):
        reply = mem_explorer.request(
            {"type": "properties", "rid": 1, "paths": ["/data/a.csv"]}
        )
        assert reply["file"]["name"] == "a.csv"
        assert reply["file"]["size"] == 8
        assert reply["file"]["url"] == "memory:///data/a.csv"
        assert "created" in reply["file"]["info"]

    def test_folders_counted_by_a_job_of_its_own(self, mem_explorer):
        mem_explorer.message({"type": "properties", "rid": 1, "paths": ["/data"]})
        job_id = mem_explorer.sent[-1][0]["job"]
        assert job_id.startswith("scan-")  # not one of the file operations' ids
        job = mem_explorer.job(job_id)
        assert (job["kind"], job["state"]) == ("properties", "done")
        result = job["result"]
        assert (result["files"], result["folders"], result["bytes"]) == (3, 2, 18)

    def test_error(self, mem_explorer):
        reply = mem_explorer.request(
            {"type": "properties", "rid": 1, "paths": ["/nope"]}
        )
        assert reply["error"].startswith("FileNotFoundError")


class TestMove:
    def move(self, explorer, paths, dest, if_exists="ask"):
        return explorer.request(
            {
                "type": "move",
                "rid": 1,
                "paths": paths,
                "dest": dest,
                "if_exists": if_exists,
            }
        )

    def test_move(self, mem_explorer):
        reply = self.move(mem_explorer, ["/data/a.csv", "/data/table"], "/other")
        assert reply["moved"] == ["a.csv"]
        assert reply["errors"] == [
            "table: folders are not moved (turn on unsafe mode first)"
        ]
        assert mem_explorer._fs.exists("/other/a.csv")
        assert not mem_explorer._fs.exists("/data/a.csv")

    @pytest.mark.parametrize(
        ("if_exists", "content"), [("skip", b"b"), ("overwrite", b"new")]
    )
    def test_conflicts(self, mem_explorer, if_exists, content):
        mem_explorer._fs.pipe_file("/data/b.txt", b"new")
        assert self.move(mem_explorer, ["/data/b.txt"], "/other")["conflicts"] == [
            "b.txt"
        ]
        self.move(mem_explorer, ["/data/b.txt"], "/other", if_exists)
        assert mem_explorer._fs.cat_file("/other/b.txt") == content

    def test_already_there(self, mem_explorer):
        assert self.move(mem_explorer, ["/other/b.txt"], "/other")["moved"] == []


class TestJobs:
    """Move, delete, paste and downloads run as jobs (see jobs.py); without a
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
                "filesystem": explorer._filesystem,
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
                "filesystem": explorer._filesystem,
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


class TestUpload:
    def test_in_pieces(self, mem_explorer):
        check = mem_explorer.request(
            {
                "type": "upload_check",
                "rid": 1,
                "dest": "/other",
                "names": ["b.txt", "c.txt"],
            }
        )
        assert check["conflicts"] == ["b.txt"]
        piece = {
            "type": "upload_chunk",
            "rid": 2,
            "id": "u1",
            "dest": "/other",
            "name": "c.txt",
        }
        assert "error" not in mem_explorer.request(
            {**piece, "last": False}, [b"hello "]
        )
        # The last piece starts a job copying the file to the storage.
        last = mem_explorer.request({**piece, "last": True}, [b"world"])
        assert last["copied"] == ["c.txt"]
        assert mem_explorer._fs.cat_file("/other/c.txt") == b"hello world"

    def test_too_large(self, memfs):
        explorer = make("/", fs=memfs, max_upload_bytes=3)
        piece = {
            "type": "upload_chunk",
            "rid": 1,
            "id": "u",
            "dest": "/",
            "name": "big",
            "last": True,
        }
        assert (
            "too large to upload (over 3 B)"
            in explorer.request(piece, [b"1234"])["error"]
        )
        assert not memfs.exists("/big")

    def test_name_cannot_escape_the_folder(self, mem_explorer):
        piece = {
            "type": "upload_chunk",
            "rid": 1,
            "id": "u",
            "dest": "/other",
            "name": "../../x.txt",
            "last": True,
        }
        mem_explorer.request(piece, [b"x"])
        assert mem_explorer._fs.exists("/other/x.txt")

    def test_from_jupyterlab_file_browser(self, mem_explorer, tmp_path):
        (tmp_path / "f.txt").write_text("f", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        content = {
            "type": "upload",
            "rid": 1,
            "root": str(tmp_path),
            "paths": ["f.txt", "sub", "nope.txt"],
            "dest": "/other",
        }
        reply = mem_explorer.request(content)
        assert reply["copied"] == ["f.txt"]
        assert reply["errors"] == [
            "nope.txt: not found from the kernel",
            "sub: folders are not uploaded (turn on unsafe mode first)",
        ]

    def test_folders_from_jupyterlab_in_unsafe_mode(self, mem_explorer, tmp_path):
        (tmp_path / "sub" / "deep").mkdir(parents=True)
        (tmp_path / "sub" / "deep" / "g.txt").write_text("g", encoding="utf-8")
        reply = mem_explorer.request(
            {
                "type": "upload",
                "rid": 1,
                "root": str(tmp_path),
                "paths": ["sub"],
                "dest": "/other",
                "unsafe": True,
            }
        )
        assert reply["copied"] == ["sub"]
        assert mem_explorer._fs.cat_file("/other/sub/deep/g.txt") == b"g"


class TestDownloadToServer:
    """Files dropped on JupyterLab's file browser, copied to the server's folders."""

    def download(self, explorer, root, dest, paths, if_exists="ask"):
        """The kernel's reply, without "type" and "rid"."""
        reply = explorer.request(
            {
                "type": "download_to_server",
                "rid": 1,
                "paths": paths,
                "root": str(root),
                "dest": dest,
                "if_exists": if_exists,
            }
        )
        return {k: v for k, v in reply.items() if k not in ("type", "rid")}

    def test_into_a_folder_relative_to_the_server_root(self, mem_explorer, tmp_path):
        (tmp_path / "notebooks" / "sub").mkdir(parents=True)
        reply = self.download(
            mem_explorer, tmp_path, "notebooks/sub", ["/data/a.csv", "/data/table"]
        )
        assert reply == {
            "copied": ["a.csv"],
            "skipped": [],
            "errors": ["table: folders are not downloaded"],
        }
        assert (tmp_path / "notebooks" / "sub" / "a.csv").read_bytes() == b"x,y\n1,2\n"
        # No temporary file left next to it.
        assert sorted(p.name for p in (tmp_path / "notebooks" / "sub").iterdir()) == [
            "a.csv"
        ]

    def test_server_root_itself(self, mem_explorer, tmp_path):
        self.download(mem_explorer, tmp_path, "", ["/other/b.txt"])
        assert (tmp_path / "b.txt").read_bytes() == b"b"

    @pytest.mark.parametrize(
        ("if_exists", "content"), [("skip", b"mine"), ("overwrite", b"b")]
    )
    def test_conflicts(self, mem_explorer, tmp_path, if_exists, content):
        (tmp_path / "b.txt").write_bytes(b"mine")
        reply = self.download(mem_explorer, tmp_path, "", ["/other/b.txt"])
        assert reply == {"conflicts": ["b.txt"]}
        assert (tmp_path / "b.txt").read_bytes() == b"mine"
        self.download(mem_explorer, tmp_path, "", ["/other/b.txt"], if_exists)
        assert (tmp_path / "b.txt").read_bytes() == content

    def test_folder_not_reachable_from_the_kernel(self, mem_explorer, tmp_path):
        reply = self.download(mem_explorer, tmp_path, "missing", ["/other/b.txt"])
        assert "folder not found from the kernel" in reply["errors"][0]

    def test_failed_copy_leaves_nothing(self, mem_explorer, tmp_path):
        reply = self.download(mem_explorer, tmp_path, "", ["/other/missing.txt"])
        assert reply["copied"] == []
        assert reply["errors"][0].startswith("missing.txt:")
        assert list(tmp_path.iterdir()) == []


def test_vendor(mem_explorer):
    assert (
        "marked"
        in mem_explorer.request({"type": "vendor", "rid": 1, "name": "marked.esm.js"})[
            "source"
        ]
    )
    assert (
        "unknown library"
        in mem_explorer.request({"type": "vendor", "rid": 1, "name": "../x"})["error"]
    )


def test_safe_name():
    assert _paths.safe_name("a/b\\c.txt") == "c.txt"
    with pytest.raises(ValueError):
        _paths.safe_name("..")


def testformat_size():
    assert format_size(10 * 1024 * 1024) == "10 MB"
    assert format_size(1536) == "1.5 KB"


def test_local_explorer_starts_in_the_folder(tmp_path):
    explorer = make(str(tmp_path))
    assert explorer._root == fsspec.filesystem("file")._strip_protocol(str(tmp_path))


# Rules refusing to copy or move /d/secret* anywhere.
DENY_SECRET = [{"rule": "deny", "src": r"memory:///d/secret.*", "dest": ".*"}]


class TestTransferPolicy:
    """Files are transferred (between filesystems) only in the directions the
    policy allows; within a filesystem, it does not apply."""

    @pytest.fixture
    def files(self, memfs):
        memfs.pipe({"/d/secret.txt": b"s", "/d/ok.txt": b"o", "/d/sub/x": b""})
        return memfs

    def test_move_within_a_filesystem_is_not_a_transfer(self, files):
        explorer = make("/", fs=files, transfer_policy=DENY_SECRET)
        reply = explorer.request(
            {
                "type": "move",
                "rid": 1,
                "paths": ["/d/secret.txt", "/d/ok.txt"],
                "dest": "/d/sub",
            }
        )
        assert (reply["moved"], reply["errors"]) == (["secret.txt", "ok.txt"], [])

    @pytest.mark.parametrize("cut", [False, True])
    def test_paste_within_a_filesystem_is_not_a_transfer(self, files, cut):
        explorer = make("/", fs=files, transfer_policy=DENY_SECRET)
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": "default",
                "files": [{"path": "/d/secret.txt"}],
                "dest": "/d/sub",
                "cut": cut,
            }
        )
        assert reply["moved" if cut else "pasted"] == ["secret.txt"]
        assert files.exists("/d/sub/secret.txt")

    def test_paste_between_storages_of_the_explorer(self, files, tmp_path):
        local = fsspec.filesystem("file")._strip_protocol(str(tmp_path))
        policy = [
            {"rule": "allow", "src": r"memory:///d/ok\.txt", "dest": ".*"},
            {"rule": "deny", "src": "memory://.*", "dest": f"{local}/.*"},
        ]
        explorer = make(
            filesystems={"mem": files, "local": str(tmp_path)}, transfer_policy=policy
        )
        explorer._filesystem = "local"
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": "mem",
                "files": [{"path": "/d/secret.txt"}, {"path": "/d/ok.txt"}],
                "dest": local,
            }
        )
        assert reply["pasted"] == ["ok.txt"]  # allowed before the deny
        assert reply["errors"][0].startswith(
            "secret.txt: not allowed by the transfer policy"
        )

    def test_paste_from_another_kernel_uses_the_url_copied(self, files, tmp_path):
        policy = [{"rule": "deny", "src": r"s3://elsewhere/.*", "dest": ".*"}]
        explorer = make(str(tmp_path), transfer_policy=policy)
        # The URL copied in the other kernel's explorer, which its _url made.
        explorer._locate = lambda url: (files, "/d/ok.txt")
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": "in another kernel",
                "filesystem": "default",
                "files": [{"path": "ok.txt", "url": "s3://elsewhere/ok.txt"}],
                "dest": explorer._root,
            }
        )
        assert (
            "not allowed by the transfer policy (s3://elsewhere/ok.txt"
            in reply["errors"][0]
        )

    def test_upload_from_jupyterlab_file_browser(self, files, tmp_path):
        (tmp_path / "f.txt").write_text("f")
        policy = [{"rule": "deny", "src": ".*", "dest": "memory:///d/sub/.*"}]
        explorer = make("/", fs=files, transfer_policy=policy)
        content = {
            "type": "upload",
            "rid": 1,
            "root": str(tmp_path),
            "paths": ["f.txt"],
        }
        assert explorer.request({**content, "dest": "/d/sub"})["copied"] == []
        assert explorer.request({**content, "dest": "/d"})["copied"] == ["f.txt"]

    def test_download_to_jupyterlab(self, files, tmp_path):
        explorer = make(
            "/",
            fs=files,
            transfer_policy=DENY_SECRET,
            download_to_jupyterlab_path=str(tmp_path),
        )
        reply = explorer.request(
            {
                "type": "download_to_jupyterlab",
                "rid": 1,
                "paths": ["/d/secret.txt", "/d/ok.txt"],
            }
        )
        assert reply["copied"] == ["ok.txt"]
        assert "secret.txt: not allowed by the transfer policy" in reply["errors"][0]
        assert not (tmp_path / "secret.txt").exists()

    def test_download_to_the_computer(self, files):
        policy = [{"rule": "deny", "dest": "browser:///secret.*"}]
        explorer = make("/", fs=files, transfer_policy=policy)
        explorer.message({"type": "download", "paths": ["/d/secret.txt", "/d/ok.txt"]})
        (secret, buffers), (ok, _) = explorer.sent[-2:]
        assert "not allowed by the transfer policy" in secret["error"]
        assert buffers is None
        assert "error" not in ok

    def test_upload_from_the_computer(self, files):
        policy = [
            {"rule": "deny", "src": "browser:///.*", "dest": "memory:///d/sub/.*"}
        ]
        explorer = make("/", fs=files, transfer_policy=policy)
        piece = {
            "type": "upload_chunk",
            "rid": 1,
            "id": "u",
            "name": "c.txt",
            "last": True,
        }
        reply = explorer.request({**piece, "dest": "/d/sub"}, [b"c"])
        assert "not allowed by the transfer policy (browser:///c.txt" in reply["error"]
        assert not files.exists("/d/sub/c.txt")
        assert explorer.request({**piece, "dest": "/d"}, [b"c"])["copied"] == ["c.txt"]

    def test_jupyterlab_side_is_jupyterlab_urls(self, files, tmp_path):
        """Transfers with JupyterLab's file browser are told apart from the
        explorer's own local storage, on the same disk."""
        (tmp_path / "f.txt").write_text("f")
        (tmp_path / "down").mkdir()
        policy = [
            {"rule": "deny", "src": "jupyterlab://.*"},
            {"rule": "deny", "dest": "jupyterlab://.*"},
        ]
        local = fsspec.filesystem("file")._strip_protocol(str(tmp_path))
        explorer = make(
            filesystems={"mem": files, "local": str(tmp_path)},
            transfer_policy=policy,
            download_to_jupyterlab_path=str(tmp_path / "down"),
        )
        # Dragged from JupyterLab's file browser.
        upload = {"type": "upload", "rid": 1, "root": str(tmp_path), "paths": ["f.txt"]}
        reply = explorer.request({**upload, "dest": "/d"})
        assert (
            f"(jupyterlab://{'' if local.startswith('/') else '/'}{local}/f.txt"
            in (reply["errors"][0])
        )
        # "Download to JupyterLab", and dropped on its file browser.
        down = {"rid": 1, "paths": ["/d/ok.txt"]}
        reply = explorer.request({**down, "type": "download_to_jupyterlab"})
        assert "→ jupyterlab://" in reply["errors"][0]
        reply = explorer.request(
            {
                **down,
                "type": "download_to_server",
                "root": str(tmp_path),
                "dest": "down",
            }
        )
        assert "→ jupyterlab://" in reply["errors"][0]
        assert not (tmp_path / "down" / "ok.txt").exists()
        # Pasted into the explorer's local storage: plain paths, allowed.
        explorer._filesystem = "local"
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": "mem",
                "files": [{"path": "/d/ok.txt"}],
                "dest": local,
            }
        )
        assert reply["pasted"] == ["ok.txt"]

    def test_invalid_policy(self, files):
        with pytest.raises(ValueError, match="transfer_policy rule 0"):
            make("/", fs=files, transfer_policy=[{"rule": "block"}])
