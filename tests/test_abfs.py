"""filesystems/abfs.py: Azure Data Lake Storage Gen2, with a fake Data Lake client
(no Azure account in tests)."""

from __future__ import annotations

from typing import Any, Self

import pytest
from adlfs import AzureBlobFileSystem
from azure.core import MatchConditions

from jupyter_storage_explorer.filesystems import abfs
from jupyter_storage_explorer.filesystems.abfs import AzureDataLakeGen2Operation
from jupyter_storage_explorer.operations import FileSystemOperations, Progress


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

        return FileSystem()


@pytest.fixture
def service(monkeypatch):
    FakeService.made, FakeService.calls = [], []
    monkeypatch.setattr(abfs, "DataLakeServiceClient", FakeService)
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
            lake, "data/raw/2026", lake, "archive/2026", Progress()
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
            lake, "data/a.csv", lake, "data/b/a.csv", Progress()
        )
        assert service.calls[0] == ("rename_file", "data", "a.csv", "data/b/a.csv")

    def test_left_to_the_next(self, lake, service, memfs, monkeypatch):
        is_dir(monkeypatch, lake, True)
        ops = AzureDataLakeGen2Operation()
        for args in [
            (lake, "data/raw", memfs, "/raw"),  # between filesystems
            (memfs, "/a", memfs, "/b"),  # not adlfs
            (lake, "data", lake, "other"),  # containers
        ]:
            with pytest.raises(FileSystemOperations.NotSupported):
                ops.move(*args, Progress())
        with pytest.raises(FileSystemOperations.NotSupported):
            ops.copy(lake, "data/a", lake, "data/b", Progress())
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
    client = AzureDataLakeGen2Operation._service_client(fs)
    assert (client.url, client.credential) == (url, credential)
