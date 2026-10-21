"""StorageExplorer's file operations: move, rename, delete, paste, cut, create a folder, properties."""

from __future__ import annotations

import pytest
from explorers import copied, entries, make, path_of, storage, without_ids
from fsspec.implementations.dirfs import DirFileSystem


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
                    "filesystem": storage(source),
                    "files": [copied(source, p) for p in files],
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

    def test_from_a_folder_view(self, memfs, tmp_path):
        """A DirFileSystem's URLs are those of the filesystem it wraps: an
        explorer of this kernel lends its filesystem, and from another kernel
        (in this process, so with the same memory) its URL is found."""
        memfs.pipe_file("/base/x.txt", b"x")
        source = make(fs=DirFileSystem("/base", memfs))
        local = make(str(tmp_path))
        path = path_of(source, "x.txt")
        assert source._url(path) == "memory:///base/x.txt"
        assert self.paste(local, [path], local._root, source=source)["pasted"] == [
            "x.txt"
        ]
        (tmp_path / "x.txt").unlink()
        source._explorer_id = "in-another-kernel"
        reply = self.paste(local, [path], local._root, source=source)
        assert reply["pasted"] == ["x.txt"]
        assert (tmp_path / "x.txt").read_bytes() == b"x"

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
                "filesystem": {"name": "default"},
                "files": [
                    {
                        "path": "/x.csv",
                        # Another kernel's memory.
                        "location": {
                            "kind": "memory",
                            "path": "/missing/x.csv",
                            "process": "another-kernel",
                        },
                    }
                ],
                "dest": local._root,
            }
        )
        assert reply["pasted"] == []
        assert reply["errors"][0].startswith("x.csv:")
        assert list(tmp_path.iterdir()) == []


class TestPasteFromElsewhere:
    """Files sent by URL from another kernel, or dropped from another page."""

    def test_unmapped_protocol_not_opened_from_its_url(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(
            "jupyter_storage_explorer.filesystems.mapper.url_to_fs",
            opened.append,
        )
        local = make(str(tmp_path))
        reply = local.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": "elsewhere",
                "filesystem": {"name": "web"},
                "files": [
                    {
                        "path": "x",
                        "location": {
                            "kind": "fsspec",
                            "url": "http://169.254.169.254/latest/meta-data/",
                        },
                    }
                ],
                "dest": local._root,
            }
        )
        assert reply["pasted"] == []
        assert "not reachable from this kernel" in reply["errors"][0]
        assert opened == [] and list(tmp_path.iterdir()) == []


class TestCut:
    """ "Cut" then "Paste": a move, within a storage or to another."""

    def paste(self, explorer, files, dest, *, source, **content):
        return without_ids(
            explorer.request(
                {
                    "type": "paste",
                    "rid": 1,
                    "explorer": source._explorer_id,
                    "filesystem": storage(source),
                    "files": [copied(source, p) for p in files],
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
        files = [copied(explorer, "/m/a.txt", "mem")]
        explorer._filesystem = "local"
        reply = without_ids(
            explorer.request(
                {
                    "type": "paste",
                    "rid": 1,
                    "explorer": explorer._explorer_id,
                    "filesystem": storage(explorer, "mem"),
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
        files = [copied(explorer, "/data/sub")]
        content = {
            "explorer": explorer._explorer_id,
            "filesystem": storage(explorer),
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
            filesystem=storage(explorer),
            files=[copied(explorer, "/data/sub")],
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
