"""StorageExplorer's Python side, driven by the messages its frontend sends."""

from __future__ import annotations

from typing import Any

import fsspec
import polars as pl
import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.query import QuerySettingsStore
from jupyter_storage_explorer.storage_explorer import _format_size, _join, _safe_name


class Explorer(StorageExplorer):
    """Keeps what would be sent to the frontend in ``sent``, as (content, buffers)."""

    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        self.__dict__.setdefault("sent", []).append((content, buffers))

    def message(self, content: dict[str, Any], buffers: Any = None) -> None:
        """Send a message as the frontend does."""
        self._on_custom_msg(self, content, buffers)

    def request(self, content: dict[str, Any], buffers: Any = None) -> dict[str, Any]:
        """Send a message as the frontend does; the last message sent back."""
        self.message(content, buffers)
        return self.sent[-1][0]


def make(*args: Any, **kwargs: Any) -> Explorer:
    kwargs.setdefault("query_settings", QuerySettingsStore())
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
            else _join(listing["dir"], name),
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
        explorer = NoCsvUrls("/d", fs=memfs, query_settings=QuerySettingsStore())
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
        opened = explorer.request({"type": "edit_open", "path": "/data/a.md"})
        explorer.request(
            {
                "type": "edit_save",
                "path": "/data/a.md",
                "text": "longer",
                "version": opened["version"],
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


def test_menu_info(mem_explorer):
    reply = mem_explorer.request({"type": "menu_info", "path": "/data/a.csv"})
    assert reply["formats"] == ["csv", "text"]
    assert reply["editable"] is True
    assert [r["library"] for r in reply["recipes"]] == ["polars", "pandas", "pyspark"]
    folder = mem_explorer.request({"type": "menu_info", "path": "/data/table"})
    assert folder["formats"] == ["delta"]
    assert folder["editable"] is False


class TestEditor:
    def test_open_and_save(self, mem_explorer):
        opened = mem_explorer.request({"type": "edit_open", "path": "/data/notes.md"})
        assert opened["text"] == "# Notes\n"
        saved = mem_explorer.request(
            {
                "type": "edit_save",
                "path": "/data/notes.md",
                "text": "new",
                "version": opened["version"],
            }
        )
        assert "error" not in saved
        assert mem_explorer._fs.cat_file("/data/notes.md") == b"new"

    def test_save_updates_the_size_listed(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        opened = mem_explorer.request({"type": "edit_open", "path": "/data/notes.md"})
        mem_explorer.request(
            {
                "type": "edit_save",
                "path": "/data/notes.md",
                "text": "longer text",
                "version": opened["version"],
            }
        )
        sizes = {e["name"]: e["size"] for e in entries(mem_explorer)}
        assert sizes == {"a.csv": 8, "notes.md": 11, "table": None}

    def test_refuses_to_overwrite_changes_made_elsewhere(self, mem_explorer):
        opened = mem_explorer.request({"type": "edit_open", "path": "/data/notes.md"})
        mem_explorer._fs.pipe_file("/data/notes.md", b"changed elsewhere")
        saved = mem_explorer.request(
            {
                "type": "edit_save",
                "path": "/data/notes.md",
                "text": "mine",
                "version": opened["version"],
            }
        )
        assert "has changed since it was opened" in saved["error"]
        assert mem_explorer._fs.cat_file("/data/notes.md") == b"changed elsewhere"

    def test_keeps_windows_line_endings(self, mem_explorer):
        mem_explorer._fs.pipe_file("/w.txt", b"a\r\nb\r\n")
        mem_explorer._write_text("/w.txt", "a\nc\n")
        assert mem_explorer._fs.cat_file("/w.txt") == b"a\r\nc\r\n"

    def test_binary_file(self, mem_explorer):
        mem_explorer._fs.pipe_file("/bin", b"\xff\xfe")
        assert (
            "not UTF-8"
            in mem_explorer.request({"type": "edit_open", "path": "/bin"})["error"]
        )


def test_download(mem_explorer):
    mem_explorer.message({"type": "download", "paths": ["/data/a.csv", "/data/table"]})
    (file_reply, buffers), (folder_reply, _) = mem_explorer.sent[-2:]
    assert (file_reply["name"], buffers) == ("a.csv", [b"x,y\n1,2\n"])
    assert "folders cannot be downloaded" in folder_reply["error"]


def test_download_to_local_not_allowed(memfs):
    memfs.pipe_file("/a.csv", b"a")
    explorer = make("/", fs=memfs, allow_download_to_local=False)
    assert explorer._allow_download_to_local is False
    explorer.message({"type": "download", "paths": ["/a.csv"]})
    reply, buffers = explorer.sent[-1]
    assert "not allowed" in reply["error"]
    assert buffers is None


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

    def test_not_offered(self, memfs, tmp_path):
        memfs.pipe_file("/a.csv", b"a")
        explorer = make("/", fs=memfs, download_to_jupyterlab_path=None)
        assert explorer._download_to_jupyterlab_path == ""
        assert "not allowed" in self.copy(explorer, ["/a.csv"])["errors"][0]


def without_ids(reply):
    return {k: v for k, v in reply.items() if k not in ("type", "rid")}


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

    def test_from_another_explorer_by_url(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/a.csv"], local._root, source=mem_explorer)
        assert reply["pasted"] == ["a.csv"]
        assert (tmp_path / "a.csv").read_bytes() == b"x,y\n1,2\n"
        assert "a.csv" in [e["name"] for e in entries(local)]

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
            ("..", "'..' is not a folder name"),
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
        assert mem_explorer.request({**piece, "last": True}, [b"world"])["done"] is True
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
            "root": str(tmp_path),
            "paths": ["f.txt", "sub", "nope.txt"],
            "dest": "/other",
        }
        reply = mem_explorer.request(content)
        assert reply["copied"] == ["f.txt"]
        assert reply["errors"] == [
            "sub: folders are not uploaded",
            "nope.txt: not found from the kernel",
        ]


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
    assert _safe_name("a/b\\c.txt") == "c.txt"
    with pytest.raises(ValueError):
        _safe_name("..")


def test_format_size():
    assert _format_size(10 * 1024 * 1024) == "10 MB"
    assert _format_size(1536) == "1.5 KB"


def test_local_explorer_starts_in_the_folder(tmp_path):
    explorer = make(str(tmp_path))
    assert explorer._root == fsspec.filesystem("file")._strip_protocol(str(tmp_path))
