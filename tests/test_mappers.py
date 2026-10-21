"""filesystems/mapper.py and mappers.py: the locations of filesystems' paths
and back, and where files copied in another kernel are."""

from __future__ import annotations

import dataclasses

import fsspec
import pytest
from adlfs import AzureBlobFileSystem
from fsspec import AbstractFileSystem
from fsspec.implementations.dbfs import DatabricksFileSystem
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems import (
    AbfsLocation,
    AzureBlobMapper,
    FileSystemMapper,
    FsspecLocation,
    GcsLocation,
    LocalLocation,
    MapperChain,
    MemoryLocation,
    S3Location,
    SftpLocation,
    default_mappers,
    same_filesystem,
)

chain = MapperChain(default_mappers())
location_of, path_in = chain.location_of, chain.path_in


def locate(location, filesystems):
    """Where an explorer with ``filesystems`` finds ``location``, sent from
    another kernel (as JSON)."""
    return chain.locate(Location.from_json(location.to_json()), filesystems)


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


class SSHFileSystem(AbstractFileSystem):
    """sshfs's: only fsspec's record of its arguments tells the server."""

    __module__ = "sshfs.spec"
    protocol = ("sftp", "ssh")


class FsspecDatabricks(AbstractFileSystem):
    """fsspec-databricks' (https://github.com/sugibuchi/fsspec-databricks)."""

    __module__ = "fsspec_databricks.spec"
    __qualname__ = "DatabricksFileSystem"
    protocol = "dbfs"
    root_marker = "/"


# Both implementations of Databricks' files: fsspec's own, and fsspec-databricks'.
DATABRICKS = [DatabricksFileSystem, FsspecDatabricks]


class OtherFileSystem(AbstractFileSystem):
    """A filesystem no mapper knows."""

    protocol = "other"

    def __init__(self, server="a", **kwargs):
        super().__init__(server, **kwargs)


class TestLocal:
    def test_url_and_plain_path(self, tmp_path):
        fs = fsspec.filesystem("file")
        path = fs._strip_protocol(str(tmp_path))
        location = location_of(fs, path)
        assert isinstance(location, LocalLocation)
        assert location.path == path
        assert location.url == f"file://{'' if path.startswith('/') else '/'}{path}"
        assert location.os_path == str(tmp_path)
        assert fs._strip_protocol(location.url) == path  # fsspec reads the URL

    def test_the_machine(self):
        location = location_of(fsspec.filesystem("file"), "/x")
        assert location.hostname

    def test_round_trip(self, tmp_path):
        fs = fsspec.filesystem("file")
        path = fs._strip_protocol(str(tmp_path))
        assert locate(location_of(fs, path), [fs]) == (fs, path)

    def test_another_machine_is_refused(self, tmp_path):
        fs = fsspec.filesystem("file")
        elsewhere = dataclasses.replace(location_of(fs, "/x"), hostname="elsewhere")
        with pytest.raises(ValueError, match="not reachable from this kernel"):
            locate(elsewhere, [fs])


class TestMemory:
    def test_url(self, memfs):
        assert location_of(memfs, "/a/b.csv").url == "memory:///a/b.csv"

    def test_the_first_that_reaches_it(self, memfs):
        other = DirFileSystem("/sub", memfs)
        local = fsspec.filesystem("file")
        location = location_of(memfs, "/x")
        assert locate(location, [local, other, memfs]) == (memfs, "/x")

    def test_else_opened_by_fsspec(self, memfs):
        fs, path = locate(location_of(memfs, "/x"), [])
        assert fs is memfs and path == "/x"

    def test_another_process_is_refused(self, memfs):
        """fsspec would open this process's memory: not where the files are."""
        with pytest.raises(ValueError, match="not reachable from this kernel"):
            locate(MemoryLocation(path="/x", process="other"), [memfs])


class TestAzure:
    def test_urls_name_the_account(self):
        location = location_of(azure(), "data/raw/x.csv")
        assert location == AbfsLocation(
            account_name="lake", container_name="data", path="raw/x.csv"
        )
        assert location.url == "abfs://data@lake.dfs.core.windows.net/raw/x.csv"

    def test_other_cloud_keeps_its_domain(self):
        fs = azure("acc", account_host="acc.blob.core.chinacloudapi.cn")
        assert location_of(fs, "c/k").url == "abfs://c@acc.dfs.core.chinacloudapi.cn/k"

    def test_without_known_host_adlfs_urls(self, monkeypatch):
        fs = azure("devstoreaccount1")
        monkeypatch.setattr(
            fs, "account_url", "http://127.0.0.1:10000/devstoreaccount1"
        )
        location = location_of(fs, "c/k")
        assert location.url == "abfs://c/k"
        assert location.account_name == "devstoreaccount1"

    def test_an_instance_reaches_its_accounts_containers(self):
        """adlfs's file system is the account; Azure's would be a container."""
        lake = azure()
        for path in ("", "data", "logs/2026/x.csv"):
            assert path_in(lake, location_of(lake, path)) == path

    def test_found_by_account(self):
        lake, other = azure(), azure("other")
        location = location_of(lake, "data/raw/x.csv")
        assert locate(location, [other, lake]) == (lake, "data/raw/x.csv")

    def test_another_accounts_location_is_not_read(self):
        assert path_in(azure(), location_of(azure("other"), "d/x")) is None

    def test_else_opened_by_fsspec(self):
        location = location_of(azure("fresh"), "data/raw/x.csv")
        fs, path = locate(location, [azure()])
        assert (fs.account_name, path) == ("fresh", "data/raw/x.csv")

    def test_credentials_are_not_part_of_it(self):
        assert same_filesystem(azure(key="a2V5"), azure(key="b3RoZXI="))
        assert not same_filesystem(azure(), azure("other"))


class TestObjectStores:
    def test_s3(self):
        fs = S3FileSystem()
        location = location_of(fs, "bucket/k.csv")
        assert location == S3Location(bucket="bucket", key="k.csv", partition="aws")
        assert location.url == "s3://bucket/k.csv"
        assert path_in(fs, location) == "bucket/k.csv"

    @pytest.mark.parametrize(
        ("kwargs", "where"),
        [
            ({}, (None, "aws")),
            ({"client_kwargs": {"region_name": "cn-north-1"}}, (None, "aws-cn")),
            ({"endpoint_url": "HTTP://MinIO:9000/"}, ("http://minio:9000", None)),
            (
                {"client_kwargs": {"endpoint_url": "http://minio:9000"}},
                ("http://minio:9000", None),
            ),
        ],
    )
    def test_s3_endpoints_and_partitions(self, kwargs, where):
        location = location_of(S3FileSystem(**kwargs), "b/k")
        assert (location.endpoint, location.partition) == where

    def test_s3_endpoints_are_told_apart(self):
        aws, minio = S3FileSystem(), S3FileSystem(endpoint_url="http://minio:9000")
        assert not same_filesystem(aws, minio)
        on_minio = location_of(minio, "bucket/k.csv")
        assert on_minio.url == location_of(aws, "bucket/k.csv").url
        assert on_minio != location_of(aws, "bucket/k.csv")
        assert path_in(aws, on_minio) is None

    def test_gcs(self):
        location = location_of(GCSFileSystem(), "bucket/k.csv")
        assert location == GcsLocation(bucket="bucket", key="k.csv")
        assert location.url == "gs://bucket/k.csv"
        emulator = location_of(GCSFileSystem("http://localhost:4443"), "b/k")
        assert emulator.endpoint == "http://localhost:4443"


class TestSFTP:
    def test_host_port_and_user(self):
        fs = SFTPFileSystem("Server.example.com", username="alice", port=2222)
        location = location_of(fs, "/home/alice/x.txt")
        assert location == SftpLocation(
            host="server.example.com", port=2222, user="alice", path="/home/alice/x.txt"
        )
        assert location.url == "sftp://alice@server.example.com:2222/home/alice/x.txt"
        assert locate(location, [fs]) == (fs, "/home/alice/x.txt")

    def test_users_are_told_apart(self):
        """A server may show each user a tree of their own."""
        alice = SFTPFileSystem("server", username="alice")
        bob = SFTPFileSystem("server", username="bob")
        assert not same_filesystem(alice, bob)
        assert path_in(bob, location_of(alice, "/x")) is None


class TestSSHFS:
    def test_host_port_and_user_from_its_arguments(self):
        for fs in (
            SSHFileSystem("Server.example.com", username="alice", port=2222),
            SSHFileSystem(host="server.example.com", username="alice", port=2222),
        ):
            location = location_of(fs, "/home/alice/x.txt")
            assert (location.host, location.port, location.user) == (
                "server.example.com",
                2222,
                "alice",
            )
            assert (
                location.url == "sftp://alice@server.example.com:2222/home/alice/x.txt"
            )

    def test_one_storage_with_fsspecs_sftp(self):
        """Files copied from one implementation are found on the other."""
        sshfs = SSHFileSystem("server", username="alice")
        sftp = SFTPFileSystem("server", username="alice")
        assert locate(location_of(sftp, "/x.txt"), [sshfs]) == (sshfs, "/x.txt")
        assert locate(location_of(sshfs, "/x.txt"), [sftp]) == (sftp, "/x.txt")
        assert same_filesystem(sshfs, sftp)


class TestDirFileSystem:
    """Views of a folder of another filesystem: its locations, under the folder."""

    def test_locations_of_the_filesystem_wrapped(self, memfs):
        view = DirFileSystem("/base", memfs)
        assert location_of(view, "x.txt") == location_of(memfs, "/base/x.txt")

    def test_found_in_the_view(self, memfs):
        view = DirFileSystem("/base", memfs)
        location = location_of(memfs, "/base/sub/x.txt")
        assert locate(location, [view]) == (view, "sub/x.txt")

    def test_not_outside_its_folder(self, memfs):
        view = DirFileSystem("/base", memfs)
        assert path_in(view, location_of(memfs, "/other/x.txt")) is None

    def test_nested(self, memfs):
        view = DirFileSystem("b", DirFileSystem("/a", memfs))
        assert location_of(view, "x.txt").url == "memory:///a/b/x.txt"
        assert path_in(view, location_of(memfs, "/a/b/x.txt")) == "x.txt"

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
        location = location_of(OtherFileSystem(), "/x")
        assert location == FsspecLocation(url="other:///x")
        assert location.protocol == "other"

    def test_the_first_with_the_protocol(self, memfs):
        """Nothing tells such filesystems apart: as before mappers."""
        b = OtherFileSystem("b")
        location = location_of(OtherFileSystem("a"), "/x")
        assert locate(location, [memfs, b]) == (b, "/x")

    def test_never_opened_from_the_url(self, memfs, monkeypatch):
        """Without a mapper, nothing tells whether a filesystem opened from a
        URL is the one the files are on: the kernel never connects there."""
        opened = []
        monkeypatch.setattr(
            "jupyter_storage_explorer.filesystems.mapper.url_to_fs",
            opened.append,
        )
        for url in ("http://169.254.169.254/latest/meta-data/", "ftp://host/x"):
            location = FsspecLocation(url=url)
            with pytest.raises(ValueError, match="not reachable from this kernel"):
                locate(location, [memfs])
        assert opened == []

    def test_same_as_fsspec_compares(self):
        assert same_filesystem(OtherFileSystem("a"), OtherFileSystem("a"))
        assert not same_filesystem(OtherFileSystem("a"), OtherFileSystem("b"))


def test_same_filesystem(memfs):
    assert same_filesystem(memfs, fsspec.filesystem("memory"))
    assert same_filesystem(memfs, memfs)
    assert not same_filesystem(memfs, fsspec.filesystem("file"))


def test_mappers_given_first(memfs):
    @dataclasses.dataclass(frozen=True, kw_only=True)
    class TestsLocation(Location):
        kind = "tests-memory"
        path: str
        url = property(lambda self: f"memory://tests{self.path}")

    class Namespaced(FileSystemMapper):
        classes = ("fsspec.implementations.memory.MemoryFileSystem",)

        def to_location(self, fs, path):
            return TestsLocation(path=path)

        def path_of(self, fs, location):
            return location.path if isinstance(location, TestsLocation) else None

    mine = MapperChain([Namespaced(), *default_mappers()])
    assert mine.location_of(memfs, "/x").url == "memory://tests/x"
    assert mine.locate(TestsLocation(path="/x"), [memfs]) == (memfs, "/x")
    assert location_of(memfs, "/x").url == "memory:///x"


class TestLevels:
    """What the storages make of their folders, for their icons."""

    def test_by_depth(self):
        levels = {type(m).__name__: m.levels for m in default_mappers()}
        assert levels["AzureBlobMapper"] == ("account", "container")
        assert levels["S3Mapper"] == levels["GCSMapper"] == ("endpoint", "bucket")
        assert levels["SFTPMapper"] == levels["SSHFSMapper"] == ("host",)
        assert levels["MemoryMapper"] == ("memory",)
        assert levels["LocalMapper"][-1] == "drive"
        assert FileSystemMapper.levels == ()

    def test_level_from_levels(self, memfs):
        level = AzureBlobMapper().level
        assert [level(memfs, p) for p in ("", "c", "/c/", "c/d")] == [
            "account",
            "container",
            "container",
            None,
        ]

    def test_in_a_dir_filesystem(self, memfs):
        assert chain.level_of(memfs, "/") == "memory"
        assert chain.level_of(DirFileSystem("/a", memfs), "") is None

    @pytest.mark.parametrize(
        ("path", "level"),
        [
            ("", "workspace"),
            ("/", "workspace"),
            ("/Volumes", "volumes"),
            ("/Volumes/main", "catalog"),
            ("Volumes/main/sales", "schema"),
            ("/Volumes/main/sales/raw", "volume"),
            ("/Volumes/main/sales/raw/2026", None),
            ("/Workspace", "workspace-files"),
            ("/Workspace/Repos", "repos"),
            ("/Workspace/Users", "users"),
            ("/Workspace/Shared", "shared"),
            ("/Workspace/Repos/me@example.com", "user"),
            ("/Workspace/Users/me@example.com", "user"),
            ("/Workspace/Repos/me@example.com/project", "repository"),
            ("/Workspace/Users/me@example.com/project", None),
            ("/Workspace/Shared/team", None),
            ("/FileStore", "legacy"),
            ("/FileStore/tables", None),
            ("/volumes/main", None),  # paths are case-sensitive
        ],
    )
    @pytest.mark.parametrize("cls", DATABRICKS)
    def test_databricks(self, cls, path, level):
        fs = cls.__new__(cls)  # no workspace
        assert chain.level_of(fs, path) == level


class TestDatabricks:
    """fsspec-databricks' DatabricksFileSystem and fsspec's own."""

    @pytest.mark.parametrize("cls", DATABRICKS)
    def test_urls_fsspec_reads(self, cls):
        """dbfs://Volumes/...: fsspec takes a protocol only before "://", and
        fsspec-databricks refuses dbfs:///Volumes/..."""
        fs = cls.__new__(cls)
        location = location_of(fs, "/Volumes/main/sales/raw/x.csv")
        assert location == FsspecLocation(url="dbfs://Volumes/main/sales/raw/x.csv")
        assert location.protocol == "dbfs"
        assert path_in(fs, location) == "/Volumes/main/sales/raw/x.csv"
        assert location_of(fs, "").url == "dbfs://"

    @pytest.mark.parametrize(
        "url", ["dbfs:/Volumes/x", "dbfs://Volumes/x", "dbfs:///Volumes/x"]
    )
    def test_any_form_found(self, url):
        fs = FsspecDatabricks.__new__(FsspecDatabricks)
        assert path_in(fs, FsspecLocation(url=url)) == "/Volumes/x"
        assert path_in(fs, FsspecLocation(url="other:///Volumes/x")) is None
