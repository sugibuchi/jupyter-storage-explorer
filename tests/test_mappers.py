"""fs_mappers: what filesystems reach, their URLs and back, and where files
copied in another kernel are."""

from __future__ import annotations

import fsspec
import pytest
from adlfs import AzureBlobFileSystem
from fsspec import AbstractFileSystem
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer.filesystems import (
    FileSystemMapper,
    MapperChain,
    default_mappers,
    same_filesystem,
)

chain = MapperChain(default_mappers())
default_url, default_location = chain.url_of, chain.locate
path_in, storage_of = chain.path_in, chain.storage_of


def locate(url, source, filesystems):
    """Where an explorer with ``filesystems`` finds ``url``, copied from
    filesystem ``source`` (maybe in another kernel)."""
    sent = storage_of(source)
    return default_location(url, sent["protocol"], sent["identifier"], filesystems)


def azure(account="lake", key="a2V5", **kwargs):
    return AzureBlobFileSystem(account_name=account, account_key=key, **kwargs)


# Stand-ins for filesystems of packages the tests do not install: mappers
# know them by their classes' names.
class S3FileSystem(AbstractFileSystem):
    __module__ = "s3fs.core"
    protocol = ("s3", "s3a")

    def __init__(self, endpoint_url=None, client_kwargs=None, **kwargs):
        super().__init__(**kwargs)
        self.endpoint_url = endpoint_url
        self.client_kwargs = client_kwargs or {}


class GCSFileSystem(AbstractFileSystem):
    __module__ = "gcsfs.core"
    protocol = ("gs", "gcs")

    def __init__(self, endpoint_url=None, **kwargs):
        super().__init__(**kwargs)
        self._endpoint = endpoint_url or "https://storage.googleapis.com"


class SFTPFileSystem(AbstractFileSystem):
    __module__ = "fsspec.implementations.sftp"
    protocol = ("sftp", "ssh")

    def __init__(self, host, **ssh_kwargs):
        super().__init__(host, **ssh_kwargs)
        self.host = host
        self.ssh_kwargs = ssh_kwargs


class OtherFileSystem(AbstractFileSystem):
    """A filesystem no mapper knows."""

    protocol = "other"

    def __init__(self, server="a", **kwargs):
        super().__init__(server, **kwargs)


class TestLocal:
    def test_plain_paths(self, tmp_path):
        fs = fsspec.filesystem("file")
        assert default_url(fs, str(tmp_path)) == str(tmp_path)

    def test_identifier_is_the_machine(self):
        identifier = storage_of(fsspec.filesystem("file"))
        assert identifier["protocol"] == "file"
        assert identifier["identifier"]["hostname"]

    def test_round_trip(self, tmp_path):
        fs = fsspec.filesystem("file")
        path = fs._strip_protocol(str(tmp_path))
        assert locate(default_url(fs, path), fs, [fs]) == (fs, path)

    def test_another_machine_is_refused(self, tmp_path):
        fs = fsspec.filesystem("file")
        with pytest.raises(ValueError, match="not reachable from this kernel"):
            default_location(str(tmp_path), "file", {"hostname": "elsewhere"}, [fs])


class TestMemory:
    def test_url(self, memfs):
        assert default_url(memfs, "/a/b.csv") == "memory:///a/b.csv"

    def test_the_first_that_reaches_it(self, memfs):
        other = DirFileSystem("/sub", memfs)
        local = fsspec.filesystem("file")
        assert locate("memory:///x", memfs, [local, other, memfs]) == (memfs, "/x")

    def test_else_opened_by_fsspec(self, memfs):
        fs, path = locate("memory:///x", memfs, [])
        assert fs is memfs and path == "/x"

    def test_another_process_is_refused(self, memfs):
        """fsspec would open this process's memory: not where the files are."""
        with pytest.raises(ValueError, match="not reachable from this kernel"):
            default_location("memory:///x", "memory", {"process": "other"}, [memfs])


class TestAzure:
    def test_urls_name_the_account(self):
        assert (
            default_url(azure(), "data/raw/x.csv")
            == "abfs://data@lake.dfs.core.windows.net/raw/x.csv"
        )

    def test_other_cloud_keeps_its_domain(self):
        fs = azure("acc", account_host="acc.blob.core.chinacloudapi.cn")
        assert default_url(fs, "c/k") == "abfs://c@acc.dfs.core.chinacloudapi.cn/k"

    def test_without_known_host_adlfs_urls(self, monkeypatch):
        fs = azure("devstoreaccount1")
        monkeypatch.setattr(
            fs, "account_url", "http://127.0.0.1:10000/devstoreaccount1"
        )
        assert default_url(fs, "c/k") == "abfs://c/k"

    def test_identifier_is_the_account_name(self):
        assert storage_of(azure()) == {
            "protocol": "abfs",
            "identifier": {"account_name": "lake"},
        }

    def test_found_by_account(self):
        lake, other = azure(), azure("other")
        url = "abfs://data@lake.dfs.core.windows.net/raw/x.csv"
        assert locate(url, lake, [other, lake]) == (lake, "data/raw/x.csv")

    def test_short_urls_are_read_with_the_identifier(self):
        """adlfs's own URLs leave the account out: the identifier tells it."""
        lake = azure()
        assert locate("abfs://data/raw/x.csv", lake, [lake]) == (lake, "data/raw/x.csv")

    def test_another_accounts_url_is_not_read(self):
        lake = azure()
        assert (
            path_in(
                lake,
                "abfs",
                {"account_name": "lake"},
                "abfs://d@other.dfs.core.windows.net/x",
            )
            is None
        )

    def test_else_opened_by_fsspec(self):
        url = "abfs://data@fresh.dfs.core.windows.net/raw/x.csv"
        fs, path = locate(url, azure("fresh"), [azure()])
        assert (fs.account_name, path) == ("fresh", "data/raw/x.csv")

    def test_credentials_are_not_part_of_it(self):
        assert same_filesystem(azure(key="a2V5"), azure(key="b3RoZXI="))
        assert not same_filesystem(azure(), azure("other"))


class TestObjectStores:
    def test_s3(self):
        fs = S3FileSystem()
        assert default_url(fs, "bucket/k.csv") == "s3://bucket/k.csv"
        assert storage_of(fs)["identifier"] == {"partition": "aws"}
        assert (
            path_in(fs, "s3", {"partition": "aws"}, "s3a://bucket/k.csv")
            == "bucket/k.csv"
        )

    @pytest.mark.parametrize(
        ("kwargs", "identifier"),
        [
            ({"client_kwargs": {"region_name": "cn-north-1"}}, {"partition": "aws-cn"}),
            ({"endpoint_url": "HTTP://MinIO:9000/"}, {"endpoint": "http://minio:9000"}),
            (
                {"client_kwargs": {"endpoint_url": "http://minio:9000"}},
                {"endpoint": "http://minio:9000"},
            ),
        ],
    )
    def test_s3_identifiers(self, kwargs, identifier):
        assert storage_of(S3FileSystem(**kwargs))["identifier"] == identifier

    def test_s3_endpoints_are_told_apart(self):
        aws, minio = S3FileSystem(), S3FileSystem(endpoint_url="http://minio:9000")
        assert not same_filesystem(aws, minio)
        with pytest.raises(ValueError, match="not reachable"):
            locate("s3://bucket/k.csv", minio, [aws])

    def test_gcs(self):
        fs = GCSFileSystem()
        assert default_url(fs, "bucket/k.csv") == "gs://bucket/k.csv"
        assert storage_of(fs) == {"protocol": "gs", "identifier": {}}
        emulator = GCSFileSystem("http://localhost:4443")
        assert storage_of(emulator)["identifier"] == {
            "endpoint": "http://localhost:4443"
        }


class TestSFTP:
    def test_host_port_and_user(self):
        fs = SFTPFileSystem("Server.example.com", username="alice", port=2222)
        assert storage_of(fs)["identifier"] == {
            "host": "server.example.com",
            "port": 2222,
            "user": "alice",
        }
        url = default_url(fs, "/home/alice/x.txt")
        assert url == "sftp://alice@server.example.com:2222/home/alice/x.txt"
        assert locate(url, fs, [fs]) == (fs, "/home/alice/x.txt")

    def test_users_are_told_apart(self):
        """A server may show each user a tree of their own."""
        alice = SFTPFileSystem("server", username="alice")
        bob = SFTPFileSystem("server", username="bob")
        assert not same_filesystem(alice, bob)
        assert (
            path_in(
                bob, "sftp", storage_of(alice)["identifier"], "sftp://alice@server:22/x"
            )
            is None
        )


class TestDirFileSystem:
    """Views of a folder of another filesystem: its URLs, under the folder."""

    def test_urls_of_the_filesystem_wrapped(self, memfs):
        view = DirFileSystem("/base", memfs)
        assert default_url(view, "x.txt") == "memory:///base/x.txt"
        assert storage_of(view) == storage_of(memfs)

    def test_found_in_the_view(self, memfs):
        view = DirFileSystem("/base", memfs)
        assert locate("memory:///base/sub/x.txt", memfs, [view]) == (view, "sub/x.txt")

    def test_not_outside_its_folder(self, memfs):
        view = DirFileSystem("/base", memfs)
        assert (
            path_in(view, *storage_of(memfs).values(), "memory:///other/x.txt") is None
        )

    def test_nested(self, memfs):
        view = DirFileSystem("b", DirFileSystem("/a", memfs))
        assert default_url(view, "x.txt") == "memory:///a/b/x.txt"
        assert (
            path_in(view, *storage_of(memfs).values(), "memory:///a/b/x.txt") == "x.txt"
        )

    def test_same_filesystem_by_folder(self, memfs):
        assert same_filesystem(
            DirFileSystem("/a", memfs), DirFileSystem("/a", fsspec.filesystem("memory"))
        )
        assert not same_filesystem(
            DirFileSystem("/a", memfs), DirFileSystem("/b", memfs)
        )
        assert not same_filesystem(DirFileSystem("/a", memfs), memfs)


class TestUnknownFilesystems:
    def test_fsspec_urls(self):
        assert default_url(OtherFileSystem(), "/x") == "other:///x"
        assert storage_of(OtherFileSystem()) == {"protocol": "other", "identifier": {}}

    def test_the_first_with_the_protocol(self, memfs):
        """Nothing tells such filesystems apart: as before mappers."""
        b = OtherFileSystem("b")
        assert locate("other:///x", OtherFileSystem("a"), [memfs, b]) == (b, "/x")

    def test_same_as_fsspec_compares(self):
        assert same_filesystem(OtherFileSystem("a"), OtherFileSystem("a"))
        assert not same_filesystem(OtherFileSystem("a"), OtherFileSystem("b"))


def test_same_filesystem(memfs):
    assert same_filesystem(memfs, fsspec.filesystem("memory"))
    assert same_filesystem(memfs, memfs)
    assert not same_filesystem(memfs, fsspec.filesystem("file"))


def test_unreachable(memfs):
    with pytest.raises(ValueError, match="not reachable from this kernel"):
        default_location("nope://x", "nope", {}, [memfs])


def test_mappers_given_first(memfs):
    class Namespaced(FileSystemMapper):
        protocol = "memory"
        classes = ("fsspec.implementations.memory.MemoryFileSystem",)

        def identifier(self, fs):
            return {"namespace": "tests"}

        def to_url(self, fs, path):
            return f"memory://tests{path}"

    mine = MapperChain([Namespaced(), *default_mappers()])
    assert mine.url_of(memfs, "/x") == "memory://tests/x"
    assert mine.storage_of(memfs)["identifier"] == {"namespace": "tests"}
    assert default_url(memfs, "/x") == "memory:///x"
