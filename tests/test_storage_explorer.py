"""StorageExplorer's Python side, driven by the messages its frontend sends."""

from __future__ import annotations

from typing import Any

import fsspec
import polars as pl
import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.query import QuerySettingsStore
from jupyter_storage_explorer.storage_explorer import _format_size, _safe_name


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


def path_of(explorer: Explorer, name: str) -> str:
    return next(e["path"] for e in explorer._entries if e["name"] == name)


class TestListing:
    def test_entries_and_tree(self, mem_explorer):
        mem_explorer._current_dir = "/data"
        entries = {e["name"]: e for e in mem_explorer._entries}
        assert entries["a.csv"]["format"] == "csv"
        assert entries["notes.md"]["format"] == "markdown"
        assert entries["table"]["type"] == "directory"
        assert entries["table"]["format"] == ""  # folders are not detected in the list
        assert [d["name"] for d in mem_explorer._tree["/"]] == ["data", "other"]
        assert mem_explorer.folder_url == "memory:///data"

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
        assert mem_explorer._entries == []

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
        assert [e["name"] for e in mem_explorer._entries] == ["table"]

    def test_folders_are_not_deleted(self, mem_explorer):
        reply = self.delete(mem_explorer, ["/data/table"])
        assert reply == {"deleted": [], "errors": ["table: folders are not deleted"]}
        assert mem_explorer._fs.exists("/data/table/_delta_log/0.json")

    def test_closes_the_preview_of_a_deleted_file(self, mem_explorer):
        mem_explorer._open_preview("/data/notes.md")
        assert mem_explorer._preview["path"] == "/data/notes.md"
        self.delete(mem_explorer, ["/data/notes.md"])
        assert mem_explorer._preview == {}

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
            "errors": ["table: folders are not pasted"],
        }
        assert mem_explorer._fs.cat_file("/other/a.csv") == b"x,y\n1,2\n"
        assert mem_explorer._fs.exists("/data/a.csv")  # copied, not moved
        assert "a.csv" in [e["name"] for e in mem_explorer._entries]

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
        assert "a.csv" in [e["name"] for e in local._entries]

    def test_folder_by_url_is_not_pasted(self, mem_explorer, tmp_path):
        local = make(str(tmp_path))
        reply = self.paste(local, ["/data/table"], local._root, source=mem_explorer)
        assert reply["errors"] == ["table: folders are not pasted"]
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
        assert reply["errors"] == ["table: folders are not moved"]
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
