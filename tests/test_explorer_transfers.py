"""StorageExplorer's uploads and downloads, and its transfer policy."""

from __future__ import annotations

import fsspec
import pytest
from explorers import make, storage

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._jobs.incoming import format_size


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


def test_safe_name():
    assert _paths.safe_name("a/b\\c.txt") == "c.txt"
    with pytest.raises(ValueError):
        _paths.safe_name("..")


def testformat_size():
    assert format_size(10 * 1024 * 1024) == "10 MB"
    assert format_size(1536) == "1.5 KB"


DENY_SECRET = [{"rule": "deny", "src": r"memory:///d/secret.*", "dest": ".*"}]


class TestTransferPolicy:
    """Files are copied and moved only in the directions the policy allows,
    within a filesystem as well as between filesystems."""

    @pytest.fixture
    def files(self, memfs):
        memfs.pipe({"/d/secret.txt": b"s", "/d/ok.txt": b"o", "/d/sub/x": b""})
        return memfs

    def test_move_within_a_filesystem(self, files):
        explorer = make("/", fs=files, transfer_policy=DENY_SECRET)
        reply = explorer.request(
            {
                "type": "move",
                "rid": 1,
                "paths": ["/d/secret.txt", "/d/ok.txt"],
                "dest": "/d/sub",
            }
        )
        assert reply["moved"] == ["ok.txt"]
        assert reply["errors"] == [
            "secret.txt: not allowed by the transfer policy "
            "(memory:///d/secret.txt → memory:///d/sub/secret.txt)"
        ]
        assert files.exists("/d/secret.txt")

    def test_rename(self, files):
        explorer = make("/", fs=files, transfer_policy=DENY_SECRET)
        reply = explorer.request(
            {"type": "rename", "rid": 1, "path": "/d/secret.txt", "name": "public.txt"}
        )
        assert "not allowed by the transfer policy" in reply["error"]
        assert files.exists("/d/secret.txt")

    @pytest.mark.parametrize("cut", [False, True])
    def test_paste_within_a_filesystem(self, files, cut):
        explorer = make("/", fs=files, transfer_policy=DENY_SECRET)
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": explorer._explorer_id,
                "filesystem": storage(explorer),
                "files": [{"path": "/d/secret.txt"}],
                "dest": "/d/sub",
                "cut": cut,
            }
        )
        assert reply["moved" if cut else "pasted"] == []
        assert "not allowed by the transfer policy" in reply["errors"][0]
        assert not files.exists("/d/sub/secret.txt")

    def test_named_groups_keep_files_in_their_folder(self, files):
        """Moves within each top folder only: the same folder on both sides."""
        files.pipe({"/e/y.txt": b"y"})
        top = r"memory:///(?P<top>[^/]+)/.*"
        policy = [
            {"rule": "allow", "src": top, "dest": top},
            {"rule": "deny", "src": "memory:///.*"},
        ]
        explorer = make("/", fs=files, transfer_policy=policy)
        move = {"type": "move", "rid": 1, "paths": ["/d/ok.txt"]}
        assert explorer.request({**move, "dest": "/d/sub"})["moved"] == ["ok.txt"]
        reply = explorer.request({**move, "paths": ["/d/sub/ok.txt"], "dest": "/e"})
        assert reply["moved"] == []
        assert "not allowed by the transfer policy" in reply["errors"][0]

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
                "filesystem": storage(explorer, "mem"),
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
        explorer._mappers.locate = lambda url, protocol, identifier, filesystems: (
            files,
            "/d/ok.txt",
        )
        reply = explorer.request(
            {
                "type": "paste",
                "rid": 1,
                "explorer": "in another kernel",
                "filesystem": {"name": "default", "protocol": "s3", "identifier": {}},
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
                "filesystem": storage(explorer, "mem"),
                "files": [{"path": "/d/ok.txt"}],
                "dest": local,
            }
        )
        assert reply["pasted"] == ["ok.txt"]

    def test_invalid_policy(self, files):
        with pytest.raises(ValueError, match="transfer_policy rule 0"):
            make("/", fs=files, transfer_policy=[{"rule": "block"}])
