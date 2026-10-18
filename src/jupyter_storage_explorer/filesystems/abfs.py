"""File operations for Azure Data Lake Storage Gen2, with its own SDK
(``azure-storage-file-datalake``, installed with the "abfs" extra)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from adlfs import AzureBlobFileSystem
from azure.core import MatchConditions
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fsspec.asyn import sync

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    within_one_filesystem,
)

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.filesystems.operation import Progress


class AzureDataLakeGen2Operation(FileSystemOperations):
    """Moves and folder creation on Azure Data Lake Storage Gen2: storage
    accounts with a hierarchical namespace, browsed with adlfs.

    There, folders exist of their own and a file or folder is renamed in one
    request, whatever its size, and never left half moved; adlfs, made for
    Blob Storage, moves file by file (copy, then delete) and does not create
    empty folders. This object does both with the Data Lake SDK, connected
    with the adlfs filesystem's own account URL and credential.

    Everything else raises ``FileSystemOperations.NotSupported``, for the
    next operations object: other operations and filesystems, moves between
    accounts (or adlfs filesystems with other credentials), containers
    themselves, and accounts without a hierarchical namespace (checked once
    per account; if it cannot be checked, e.g. for lack of permission, the
    account is taken to have none).

    Needs ``adlfs`` and ``azure-storage-file-datalake``, installed with
    ``pip install "jupyter-storage-explorer[abfs]"``.

    Examples
    --------
    >>> from jupyter_storage_explorer.filesystems.abfs import AzureDataLakeGen2Operation
    >>> StorageExplorer(
    ...     "abfs://lake@myaccount.dfs.core.windows.net/raw",
    ...     operations=[AzureDataLakeGen2Operation()],
    ... )
    """

    def __init__(self) -> None:
        # Account URL -> whether it has a hierarchical namespace.
        self._hierarchical: dict[str, bool] = {}
        self._lock = threading.Lock()

    def move(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
        *,
        same: bool | None = None,
    ) -> None:
        if not within_one_filesystem(source_fs, target_fs, same):
            raise self.NotSupported
        fs = self._gen2(source_fs)
        container, key = _split(source)
        new_container, new_key = _split(target)
        if not key or not new_key:
            raise self.NotSupported  # containers: adlfs's own
        progress.working_on(_paths.basename(source))
        is_dir = fs.isdir(source)
        sync(
            fs.loop,
            self._rename,
            fs,
            container,
            key,
            f"{new_container}/{new_key}",
            is_dir,
        )
        fs.invalidate_cache(source)
        fs.invalidate_cache(target)

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        fs = self._gen2(fs)
        container, key = _split(path)
        if not key:
            raise self.NotSupported  # a container: adlfs's own
        sync(fs.loop, self._create_directory, fs, container, key)
        fs.invalidate_cache(path)

    def _gen2(self, fs: AbstractFileSystem) -> AzureBlobFileSystem:
        """``fs``, if an adlfs filesystem of an account with a hierarchical
        namespace, usable from this thread; else NotSupported."""
        if not isinstance(fs, AzureBlobFileSystem) or fs.asynchronous:
            raise self.NotSupported
        with self._lock:
            known = self._hierarchical.get(fs.account_url)
        if known is None:
            known = self._has_hierarchical_namespace(fs)
            with self._lock:
                self._hierarchical[fs.account_url] = known
        if not known:
            raise self.NotSupported
        return fs

    @staticmethod
    def _has_hierarchical_namespace(fs: AzureBlobFileSystem) -> bool:
        """Whether ``fs``'s account has a hierarchical namespace (Data Lake
        Gen2), asked with adlfs's own Blob Storage client."""
        try:
            info = sync(fs.loop, fs.service_client.get_account_information)
        except Exception:
            return False  # cannot tell: leave it to adlfs
        return bool(info.get("is_hns_enabled"))

    @staticmethod
    def _service_client(fs: AzureBlobFileSystem) -> DataLakeServiceClient:
        """A Data Lake client for ``fs``'s account, connected as adlfs connects
        (its ``do_connect``): with its connection string, else its account URL
        (the Data Lake endpoint, "dfs" for "blob") and credential or account
        key, else its SAS token. Made within the filesystem's event loop, on
        which it is used, then closed."""
        if fs.connection_string:
            return DataLakeServiceClient.from_connection_string(fs.connection_string)
        url = fs.account_url.replace(".blob.", ".dfs.", 1)
        credential: Any = fs.credential if fs.credential is not None else fs.account_key
        if credential is None and fs.sas_token:
            url = f"{url}?{fs.sas_token.lstrip('?')}"
        return DataLakeServiceClient(url, credential=credential)

    async def _rename(
        self,
        fs: AzureBlobFileSystem,
        container: str,
        key: str,
        new_name: str,
        is_dir: bool,
    ) -> None:
        """Rename ``key`` of ``container`` to ``new_name`` ("container/key")."""
        async with self._service_client(fs) as service:
            file_system = service.get_file_system_client(container)
            if is_dir:
                await file_system.get_directory_client(key).rename_directory(new_name)
            else:
                await file_system.get_file_client(key).rename_file(new_name)

    async def _create_directory(
        self, fs: AzureBlobFileSystem, container: str, key: str
    ) -> None:
        """Create directory ``key`` in ``container`` (and its parents), failing
        if it exists."""
        async with self._service_client(fs) as service:
            file_system = service.get_file_system_client(container)
            await file_system.create_directory(
                key, match_condition=MatchConditions.IfMissing
            )


def _split(path: str) -> tuple[str, str]:
    """("container", "key") of an adlfs path "container/key"."""
    container, _, key = path.strip("/").partition("/")
    return container, key.strip("/")
