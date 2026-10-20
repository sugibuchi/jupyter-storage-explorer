"""StorageExplorer's folders: the list, the tree and switching storages."""

from __future__ import annotations

import fsspec
import pytest
from explorers import Explorer, entries, make, path_of

from jupyter_storage_explorer import Location
from jupyter_storage_explorer._explorer.states import ExplorerStates


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

    def test_locations_on_request(self, mem_explorer):
        reply = mem_explorer.request(
            {"type": "locations", "rid": 1, "paths": ["/data/a.csv", "/data"]}
        )
        [file, folder] = reply["locations"]
        assert (file["url"], folder["url"]) == (
            "memory:///data/a.csv",
            "memory:///data",
        )
        assert file["path"] is None  # plain paths are for local files only
        assert Location.from_json(file["location"]) == mem_explorer._location_of(
            "/data/a.csv"
        )

    def test_local_paths_on_request(self, tmp_path):
        (tmp_path / "a.csv").write_bytes(b"x")
        local = Explorer(str(tmp_path), states=ExplorerStates())
        assert local._local_paths
        path = path_of(local, "a.csv")
        [reply] = local.request({"type": "locations", "rid": 1, "paths": [path]})[
            "locations"
        ]
        assert reply["path"] == str(tmp_path / "a.csv")  # the system's form
        assert reply["url"].startswith("file:///")

    def test_items_without_url(self, memfs):
        class NoCsvUrls(Explorer):
            def _location_of(self, path):
                if path.endswith((".csv", "/sub")):
                    return None
                return super()._location_of(path)

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
            ({"supports": [object()]}, TypeError),
            ({"format_options": {"typo": 1}}, ValueError),
        ],
    )
    def test_invalid_arguments(self, kwargs, error):
        with pytest.raises(error):
            make(**kwargs)

    def test_storage_options_with_fs(self, memfs):
        with pytest.raises(TypeError, match="storage options"):
            make(fs=memfs, anon=True)


def test_local_explorer_starts_in_the_folder(tmp_path):
    explorer = make(str(tmp_path))
    assert explorer._root == fsspec.filesystem("file")._strip_protocol(str(tmp_path))
