"""abfs-support's operation: Azure Data Lake Storage Gen2, with a fake Data Lake client
(no Azure account in tests); and its entry point."""

from __future__ import annotations

import asyncio
from importlib.metadata import entry_points
from typing import Any, Self

import pytest
from adlfs import AzureBlobFileSystem
from azure.core import MatchConditions
from jupyter_storage_explorer_abfs_support import (
    AbfsSupport,
    AbfsSupportOptions,
    AzureDataLakeGen2Operation,
    _azure,
)

from jupyter_storage_explorer._jobs.progress import JobProgress
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    OperationCancelled,
)


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="abfs-support"
    )
    plugin = entry_point.load()(AbfsSupportOptions(concurrency=8))
    assert isinstance(plugin, AbfsSupport)
    assert plugin.description == "Azure Data Lake Storage support for Storage Explorer"
    [operation] = plugin.filesystem_operations
    assert isinstance(operation, AzureDataLakeGen2Operation)
    assert operation.concurrency == 8  # the plugin's option


class FakeService:
    """The parts of the async DataLakeServiceClient used, recording calls."""

    calls: list[tuple[Any, ...]]

    def __init__(self, url: str, credential: Any = None) -> None:
        self.url, self.credential = url, credential
        FakeService.made.append(self)

    @classmethod
    def from_connection_string(cls, conn_str: str) -> FakeService:
        return cls(f"connection string {conn_str}")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        FakeService.calls.append(("closed",))

    def get_file_system_client(self, container: str) -> Any:
        calls = FakeService.calls

        class Path:
            def __init__(self, key: str) -> None:
                self.key = key

            async def rename_directory(self, new_name: str) -> None:
                calls.append(("rename_directory", container, self.key, new_name))

            async def rename_file(self, new_name: str) -> None:
                calls.append(("rename_file", container, self.key, new_name))

        class FileSystem:
            get_directory_client = get_file_client = Path

            async def create_directory(self, key: str, **kwargs: Any) -> None:
                calls.append(("create_directory", container, key, kwargs))

            async def get_paths(self, path: str, recursive: bool = True) -> Any:
                """The folder's items, from ``FakeService.folders``."""
                calls.append(("get_paths", container, path, recursive))
                for name, size in FakeService.folders[f"{container}/{path}"]:
                    yield type(
                        "PathProperties",
                        (),
                        {
                            "name": f"{path}/{name}",
                            "is_directory": size is None,
                            "content_length": size or 0,
                        },
                    )()

        return FileSystem()


@pytest.fixture
def service(monkeypatch):
    FakeService.made, FakeService.calls, FakeService.folders = [], [], {}
    monkeypatch.setattr(_azure, "DataLakeServiceClient", FakeService)
    return FakeService


@pytest.fixture
def lake(monkeypatch):
    """An adlfs filesystem (account key) of an account with a hierarchical namespace."""
    fs = AzureBlobFileSystem(account_name="lake", account_key="a2V5")
    monkeypatch.setattr(
        AzureDataLakeGen2Operation,
        "_has_hierarchical_namespace",
        staticmethod(lambda fs: True),
    )
    return fs


def is_dir(monkeypatch, fs, value: bool) -> None:
    monkeypatch.setattr(fs, "isdir", lambda path: value)


class TestMove:
    def test_folder_renamed_in_one_request(self, lake, service, monkeypatch):
        is_dir(monkeypatch, lake, True)
        AzureDataLakeGen2Operation().move(
            lake, "data/raw/2026", lake, "archive/2026", JobProgress(), same=True
        )
        assert service.calls == [
            ("rename_directory", "data", "raw/2026", "archive/2026"),
            ("closed",),
        ]
        # Connected with the filesystem's account (its Data Lake endpoint) and key.
        assert service.made[0].url == "https://lake.dfs.core.windows.net"
        assert service.made[0].credential == "a2V5"

    def test_file(self, lake, service, monkeypatch):
        is_dir(monkeypatch, lake, False)
        AzureDataLakeGen2Operation().move(
            lake, "data/a.csv", lake, "data/b/a.csv", JobProgress(), same=True
        )
        assert service.calls[0] == ("rename_file", "data", "a.csv", "data/b/a.csv")

    def test_left_to_the_next(self, lake, service, memfs, monkeypatch):
        is_dir(monkeypatch, lake, True)
        ops = AzureDataLakeGen2Operation()
        for *args, same in [
            (lake, "data/raw", memfs, "/raw", False),  # between filesystems
            (memfs, "/a", memfs, "/b", True),  # not adlfs
            (lake, "data", lake, "other", True),  # containers
        ]:
            with pytest.raises(FileSystemOperations.NotSupported):
                ops.move(*args, JobProgress(), same=same)
        assert service.calls == []


def test_mkdir(lake, service):
    AzureDataLakeGen2Operation().mkdir(lake, "data/raw/new")
    assert service.calls[0] == (
        "create_directory",
        "data",
        "raw/new",
        {"match_condition": MatchConditions.IfMissing},
    )
    with pytest.raises(FileSystemOperations.NotSupported):
        AzureDataLakeGen2Operation().mkdir(lake, "newcontainer")


def test_without_a_hierarchical_namespace(service, monkeypatch):
    """Checked once per account; Blob Storage accounts are left to adlfs."""
    fs = AzureBlobFileSystem(account_name="blobs", account_key="a2V5")
    asked = []

    async def account_information() -> dict[str, Any]:
        asked.append(1)
        return {"is_hns_enabled": False}

    monkeypatch.setattr(
        fs.service_client, "get_account_information", account_information
    )
    ops = AzureDataLakeGen2Operation()
    for _ in range(2):
        with pytest.raises(FileSystemOperations.NotSupported):
            ops.mkdir(fs, "data/new")
    assert asked == [1]
    assert service.calls == []


@pytest.mark.parametrize(
    ("arguments", "url", "credential"),
    [
        (
            {"sas_token": "sv=1&sig=x"},
            "https://acc.dfs.core.windows.net?sv=1&sig=x",
            None,
        ),
        (
            {"connection_string": "AccountName=acc;AccountKey=a2V5"},
            "connection string AccountName=acc;AccountKey=a2V5",
            None,
        ),
    ],
)
def test_connected_as_adlfs_is(arguments, url, credential, service):
    kwargs = {} if "connection_string" in arguments else {"account_name": "acc"}
    fs = AzureBlobFileSystem(**kwargs, **arguments)
    client = AzureDataLakeGen2Operation._datalake_service_client(fs)
    assert (client.url, client.credential) == (url, credential)


class FakeBlobs:
    """The parts of the async BlobServiceClient that copies use: each blob's
    copy ends with the statuses given (``pending`` ones polled), "success"
    by default. Made in place of BlobServiceClient(url, credential)."""

    def __init__(self, statuses: dict[str, list[str]] | None = None) -> None:
        self.statuses = statuses or {}
        self.connected: list[tuple[str, Any]] = []
        self.closed = False
        self.descriptions: dict[str, str] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.active = self.most_active = 0

    def __call__(self, url: str, credential: Any = None) -> Self:
        self.connected.append((url, credential))
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    def get_blob_client(self, container: str, key: str) -> Any:
        blobs, name = self, f"{container}/{key}"

        class Properties:
            def __init__(self, status: str) -> None:
                description = blobs.descriptions.get(name)
                self.copy = type(
                    "Copy", (), {"status": status, "status_description": description}
                )()

        class Blob:
            url = f"https://lake.blob.core.windows.net/{name}"

            async def start_copy_from_url(self, source_url: str) -> dict[str, Any]:
                blobs.calls.append(("copy", source_url, name))
                self.left = list(blobs.statuses.get(name, ["success"]))
                blobs.active += 1
                blobs.most_active = max(blobs.most_active, blobs.active)
                await asyncio.sleep(0)
                return self._status()

            async def get_blob_properties(self) -> Properties:
                return Properties(self._status()["copy_status"])

            def _status(self) -> dict[str, Any]:
                status = self.left.pop(0) if len(self.left) > 1 else self.left[0]
                if status != "pending":
                    blobs.active -= 1
                return {"copy_status": status, "copy_id": f"id-{name}"}

            async def abort_copy(self, copy_id: str) -> None:
                blobs.calls.append(("abort", copy_id))

            async def delete_blob(self) -> None:
                blobs.calls.append(("delete", name))

        return Blob()


@pytest.fixture
def blobs(monkeypatch):
    fake = FakeBlobs()
    monkeypatch.setattr(_azure, "BlobServiceClient", fake)
    return fake


def tree(folders: dict[str, list[tuple[str, int | None]]]) -> None:
    """The Data Lake client lists ``folders``: "container/folder" -> [(name,
    size, or None for a folder)]."""
    FakeService.folders = folders


def ops(**kwargs: Any) -> AzureDataLakeGen2Operation:
    result = AzureDataLakeGen2Operation(**kwargs)
    result.POLL_INTERVALS = (0.0,)
    return result


class TestCopy:
    """Copies within an account, by the storage itself (Copy Blob)."""

    def test_file(self, lake, service, blobs, monkeypatch):
        is_dir(monkeypatch, lake, False)
        progress = JobProgress()
        ops().copy(lake, "data/a.csv", lake, "other/b.csv", progress, same=True)
        assert blobs.calls == [
            ("copy", "https://lake.blob.core.windows.net/data/a.csv", "other/b.csv")
        ]
        # The Data Lake client's account: its Blob endpoint, and the same key.
        assert blobs.connected == [("https://lake.blob.core.windows.net", "a2V5")]
        assert blobs.closed
        assert progress.snapshot()["files_done"] == 1

    def test_folder_files_of_each_folder_at_once(
        self, lake, service, blobs, monkeypatch
    ):
        is_dir(monkeypatch, lake, True)
        tree(
            {
                "data/raw": [
                    ("a", 1),
                    ("b", 2),
                    ("c", 3),
                    ("sub", None),
                    ("empty", None),
                ],
                "data/raw/sub": [("d", 4)],
                "data/raw/empty": [],
            },
        )
        # A copy pending for two polls: the other copies start meanwhile.
        blobs.statuses = {
            f"data/copy/{n}": ["pending", "pending", "success"] for n in "abc"
        }
        progress = JobProgress()
        ops(concurrency=2).copy(
            lake, "data/raw", lake, "data/copy", progress, same=True
        )
        copied = sorted(name for kind, _, name in blobs.calls if kind == "copy")
        assert copied == [
            "data/copy/a",
            "data/copy/b",
            "data/copy/c",
            "data/copy/sub/d",
        ]
        assert blobs.most_active == 2  # at once, but at most concurrency
        # Folders created first, empty ones too.
        created = sorted(c[2] for c in service.calls if c[0] == "create_directory")
        assert created == ["copy", "copy/empty", "copy/sub"]
        # Each folder listed on its own, with the Data Lake API.
        listed = sorted(c[1:] for c in service.calls if c[0] == "get_paths")
        assert listed == [
            ("data", "raw", False),
            ("data", "raw/empty", False),
            ("data", "raw/sub", False),
        ]
        snapshot = progress.snapshot()
        assert (snapshot["files_done"], snapshot["bytes_done"]) == (4, 10)

    @pytest.mark.parametrize(
        "ending",
        [
            (
                "failed",
                "500 InternalError",
                r"a\.csv: copy failed \(500 InternalError\)",
            ),
            ("aborted", None, r"a\.csv: copy aborted$"),
            ("unknown", None, r"a\.csv: unexpected copy status 'unknown'"),
        ],
    )
    def test_copy_that_did_not_succeed_is_deleted(
        self, lake, blobs, monkeypatch, ending
    ):
        """Ended without success: its target deleted, not aborted (it ended).
        ``ending``: the status, its description, and the error expected."""
        status, description, message = ending
        is_dir(monkeypatch, lake, False)
        blobs.statuses = {"data/b.csv": ["pending", status]}
        if description:
            blobs.descriptions = {"data/b.csv": description}
        with pytest.raises(OSError, match=message):
            ops().copy(lake, "data/a.csv", lake, "data/b.csv", JobProgress(), same=True)
        assert blobs.calls[-1] == ("delete", "data/b.csv")
        assert not any(c[0] == "abort" for c in blobs.calls)

    def test_failed_at_once(self, lake, service, blobs, monkeypatch):
        """A copy may end in its first answer, without polling."""
        is_dir(monkeypatch, lake, False)
        blobs.statuses = {"data/b.csv": ["failed"]}
        with pytest.raises(OSError, match="copy failed"):
            ops().copy(lake, "data/a.csv", lake, "data/b.csv", JobProgress(), same=True)
        assert blobs.calls[-1] == ("delete", "data/b.csv")

    def test_cancelled_copies_are_deleted(self, lake, service, blobs, monkeypatch):
        is_dir(monkeypatch, lake, True)
        tree({"data/raw": [(n, 1) for n in "abcd"]})
        blobs.statuses = {f"data/copy/{n}": ["pending"] for n in "abcd"}
        progress = JobProgress()
        started = []

        async def cancel_soon() -> None:
            await asyncio.sleep(0.05)
            progress.cancel()

        original = blobs.get_blob_client

        def get_blob_client(container: str, key: str) -> Any:
            blob = original(container, key)
            start = blob.start_copy_from_url

            async def start_copy(url: str) -> dict[str, Any]:
                if not started:
                    asyncio.get_running_loop().create_task(cancel_soon())
                started.append(key)
                return await start(url)

            blob.start_copy_from_url = start_copy
            return blob

        blobs.get_blob_client = get_blob_client
        with pytest.raises(OperationCancelled):
            ops(concurrency=2).copy(
                lake, "data/raw", lake, "data/copy", progress, same=True
            )
        # The two copies running were aborted and deleted; no other started.
        assert len(started) == 2
        deleted = sorted(c[1] for c in blobs.calls if c[0] == "delete")
        assert deleted == sorted(f"data/{k}" for k in started)
        assert sum(1 for c in blobs.calls if c[0] == "abort") == 2

    @pytest.mark.parametrize("bad", ["..", "a\\..\\x"])
    def test_names_leaving_the_folder_refused(
        self, lake, service, blobs, monkeypatch, bad
    ):
        """Checked before anything of the folder is created or copied."""
        is_dir(monkeypatch, lake, True)
        tree({"data/raw": [("ok.csv", 1), (bad, 2)]})
        with pytest.raises(ValueError, match="is not a file name"):
            ops().copy(lake, "data/raw", lake, "data/copy", JobProgress(), same=True)
        assert blobs.calls == []
        assert not [c for c in service.calls if c[0] == "create_directory"]

    def test_left_to_the_next(self, lake, service, blobs, monkeypatch):
        is_dir(monkeypatch, lake, False)
        other = AzureBlobFileSystem(account_name="other", account_key="a2V5")
        for *args, same in [
            (lake, "data/a.csv", other, "data/a.csv", False),  # between accounts
            (lake, "data", lake, "copy", True),  # containers
        ]:
            with pytest.raises(FileSystemOperations.NotSupported):
                ops().copy(*args, JobProgress(), same=same)
        assert blobs.calls == []
