"""File operations for Azure Data Lake Storage Gen2, with its own SDK
(``azure-storage-file-datalake``, installed with the plugin's "full" extra)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import threading
import time
from typing import TYPE_CHECKING, Any

from fsspec.asyn import sync

from jupyter_storage_explorer import _paths, get_logger
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    OperationCancelled,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from types import ModuleType

    from adlfs import AzureBlobFileSystem
    from azure.storage.blob.aio import BlobServiceClient
    from azure.storage.filedatalake.aio import DataLakeServiceClient
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.filesystems.operation import Progress

log = get_logger(__name__)


class AzureDataLakeGen2Operation(FileSystemOperations):
    """Moves, copies, folder deletion and folder creation on Azure Data Lake
    Storage Gen2: storage accounts with a hierarchical namespace, browsed
    with adlfs.

    There, folders exist of their own. A file or folder is renamed in one
    request, whatever its size, and never left half moved. A folder is
    deleted in one request too, with everything in it. adlfs, made for Blob
    Storage, moves and deletes file by file and does not create empty
    folders. This object does these with the Data Lake SDK, connected with
    the adlfs filesystem's own account URL and credential. Its progress then
    shows no file until the end.

    Copies within an account are done by the storage itself (Blob Storage's
    Copy Blob, started with ``start_copy_from_url`` and polled until it
    ends), so no byte goes through the kernel: the files of a folder at a
    time, at most ``concurrency`` of them at once, with its folders (empty
    ones too) created first. A file whose copy fails or is cancelled is
    deleted, never left partly copied.

    Moves and copies are done only within one account (``same``, as the
    explorer's filesystem mappers tell). Everything else raises
    ``FileSystemOperations.NotSupported``, for the next operations object:
    other operations and filesystems, moves and copies between accounts (copies between accounts have prerequisites of
    their own, e.g. the source readable by the target's credential),
    deletions of files (one request with adlfs too), containers themselves, and accounts without a hierarchical namespace
    (checked once per account; if it cannot be checked, e.g. for lack of
    permission, the account is taken to have none).

    Parameters
    ----------
    concurrency : int, default 64
        Most files copied at once.

    Needs ``adlfs`` and ``azure-storage-file-datalake``, installed with
    ``pip install "jupyter-storage-explorer[abfs]"``; without them, it leaves
    every operation to the next. The plugin ``abfs-support`` gives it to
    every explorer.
    """

    # Seconds between two polls of a copy still pending, growing to the last.
    POLL_INTERVALS = (0.2, 0.5, 1.0, 2.0)

    def __init__(self, concurrency: int = 64) -> None:
        self.concurrency = concurrency
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
        same: bool,
    ) -> None:
        if not same:
            raise self.NotSupported  # between accounts (see the class docstring)
        fs = self._gen2(source_fs)
        container, key = _split(source)
        new_container, new_key = _split(target)
        if not key or not new_key:
            raise self.NotSupported  # containers: adlfs's own
        progress.working_on(_paths.basename(source))
        is_dir = fs.isdir(source)
        new_name = f"{new_container}/{new_key}"
        started = time.monotonic()
        self._run_with_datalake_service(
            fs,
            lambda service: self._rename(service, container, key, new_name, is_dir),
        )
        log.info(
            "Renamed %s to %s with the Data Lake API in %.1f s",
            source,
            target,
            time.monotonic() - started,
        )
        fs.invalidate_cache(source)
        fs.invalidate_cache(target)

    def copy(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
        *,
        same: bool,
    ) -> None:
        if not same:
            raise self.NotSupported  # between accounts (see the class docstring)
        fs = self._gen2(source_fs)
        if not _split(source)[1] or not _split(target)[1]:
            raise self.NotSupported  # containers: adlfs's own
        is_dir = fs.isdir(source)
        started = time.monotonic()
        try:
            self._run_with_datalake_service(
                fs,
                lambda service: self._copy(service, source, target, is_dir, progress),
            )
        finally:
            fs.invalidate_cache(target)
        log.info(
            "Copied %s to %s within the account (Copy Blob) in %.1f s",
            source,
            target,
            time.monotonic() - started,
        )

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        fs = self._gen2(fs)
        container, key = _split(path)
        if not key:
            raise self.NotSupported  # a container: adlfs's own
        if not fs.isdir(path):
            raise self.NotSupported  # a file: one request with adlfs too
        progress.working_on(_paths.basename(path))
        started = time.monotonic()
        try:
            self._run_with_datalake_service(
                fs, lambda service: self._delete_directory(service, container, key)
            )
        finally:
            fs.invalidate_cache(path)
        log.info(
            "Deleted %s with the Data Lake API in %.1f s",
            path,
            time.monotonic() - started,
        )

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        fs = self._gen2(fs)
        container, key = _split(path)
        if not key:
            raise self.NotSupported  # a container: adlfs's own
        self._run_with_datalake_service(
            fs, lambda service: self._create_directory(service, container, key)
        )
        fs.invalidate_cache(path)

    def _gen2(self, fs: AbstractFileSystem) -> AzureBlobFileSystem:
        """``fs``, if an adlfs filesystem of an account with a hierarchical
        namespace, usable from this thread; else NotSupported (also without
        adlfs or the Data Lake SDK)."""
        try:
            azure = _azure()
        except ImportError:
            raise self.NotSupported from None
        if not isinstance(fs, azure.AzureBlobFileSystem) or fs.asynchronous:
            raise self.NotSupported
        with self._lock:
            known = self._hierarchical.get(fs.account_url)
        if known is None:
            known = self._has_hierarchical_namespace(fs)
            with self._lock:
                self._hierarchical[fs.account_url] = known
            log.info(
                "%s: %s",
                fs.account_url,
                "a hierarchical namespace, so moves and copies use the Data Lake API"
                if known
                else "no hierarchical namespace, so adlfs moves and copies",
            )
        if not known:
            raise self.NotSupported
        return fs

    @staticmethod
    def _has_hierarchical_namespace(fs: AzureBlobFileSystem) -> bool:
        """Whether ``fs``'s account has a hierarchical namespace (Data Lake
        Gen2), asked with adlfs's own Blob Storage client."""
        try:
            info = sync(fs.loop, fs.service_client.get_account_information)
        except Exception as exc:
            # The error's type only: Azure's messages may quote request URLs.
            log.warning(
                "%s: cannot tell whether it has a hierarchical namespace (%s), "
                "e.g. for lack of permission: adlfs moves and copies",
                fs.account_url,
                type(exc).__name__,
            )
            return False  # cannot tell: leave it to adlfs
        return bool(info.get("is_hns_enabled"))

    @staticmethod
    def _datalake_service_client(fs: AzureBlobFileSystem) -> DataLakeServiceClient:
        """A Data Lake client for ``fs``'s account, connected as adlfs connects
        (its ``do_connect``): with its connection string, else its account URL
        (the Data Lake endpoint, "dfs" for "blob") and credential or account
        key, else its SAS token. Made within the filesystem's event loop, on
        which it is used, then closed."""
        if fs.connection_string:
            return _azure().DataLakeServiceClient.from_connection_string(
                fs.connection_string
            )
        url = fs.account_url.replace(".blob.", ".dfs.", 1)
        credential: Any = fs.credential if fs.credential is not None else fs.account_key
        if credential is None and fs.sas_token:
            url = f"{url}?{fs.sas_token.lstrip('?')}"
        return _azure().DataLakeServiceClient(url, credential=credential)

    def _run_with_datalake_service(
        self,
        fs: AzureBlobFileSystem,
        work: Callable[[DataLakeServiceClient], Awaitable[None]],
    ) -> None:
        """Run ``work(service)``, the coroutine of an operation, on ``fs``'s
        event loop (where its clients belong) and wait for it: ``service`` is a
        Data Lake client of ``fs``'s account (see ``_datalake_service_client``),
        closed afterwards. Its errors, a cancel included, are raised here."""

        async def with_service() -> None:
            async with self._datalake_service_client(fs) as service:
                await work(service)

        sync(fs.loop, with_service)

    @staticmethod
    async def _rename(
        service: DataLakeServiceClient,
        container: str,
        key: str,
        new_name: str,
        is_dir: bool,
    ) -> None:
        """Rename ``key`` of ``container`` to ``new_name`` ("container/key")."""
        file_system = service.get_file_system_client(container)
        if is_dir:
            await file_system.get_directory_client(key).rename_directory(new_name)
        else:
            await file_system.get_file_client(key).rename_file(new_name)

    @staticmethod
    async def _delete_directory(
        service: DataLakeServiceClient, container: str, key: str
    ) -> None:
        """Delete directory ``key`` of ``container``, with all it holds. With
        OAuth, the storage may check ACLs in several requests (a paginated
        delete), which the SDK sends until the directory is gone."""
        file_system = service.get_file_system_client(container)
        await file_system.get_directory_client(key).delete_directory()

    @staticmethod
    async def _create_directory(
        service: DataLakeServiceClient, container: str, key: str
    ) -> None:
        """Create directory ``key`` in ``container`` (and its parents), failing
        if it exists."""
        await service.get_file_system_client(container).create_directory(
            key, match_condition=_azure().MatchConditions.IfMissing
        )

    async def _copy(
        self,
        service: DataLakeServiceClient,
        source: str,
        target: str,
        is_dir: bool,
        progress: Progress,
    ) -> None:
        """Copy file or folder ``source`` to ``target`` ("container/key"),
        the files of each folder at once, at most ``concurrency`` copies at a
        time. The first error, or a cancel, stops the others. Folders are
        listed and created with ``service``; files are copied with Blob
        Storage's API (Copy Blob, which Data Lake has no counterpart of), on
        the same account and credential."""
        copies = asyncio.Semaphore(self.concurrency)
        async with _blob_service_client(service) as blobs:
            if not is_dir:
                await self._copy_file(
                    blobs, source, target, size=None, copies=copies, progress=progress
                )
                return

            async def folder(src: str, dest: str) -> None:
                progress.check()
                # The folder's own items (paths within the container), with
                # the Data Lake API: its subfolders are listed as they are copied.
                src_container, src_key = _split(src)
                listing = service.get_file_system_client(src_container).get_paths(
                    path=src_key, recursive=False
                )
                paths = [path async for path in listing]
                # Checked before anything of the folder is copied: a name the
                # target would read as a path ("..", or with a backslash, which
                # Azure may take as "/") would put files outside ``dest``.
                for path in paths:
                    name = _paths.basename(path.name)
                    if name in (".", "..") or "\\" in name:
                        raise ValueError(
                            f"{_paths.basename(src)}: not copied, as a name in it "
                            f"is not a file name ({path.name})"
                        )
                container, key = _split(dest)
                await self._create_directory(service, container, key)
                async with asyncio.TaskGroup() as group:
                    for path in paths:
                        name = _paths.basename(path.name)
                        item, child = f"{src_container}/{path.name}", f"{dest}/{name}"
                        if path.is_directory:
                            group.create_task(folder(item, child))
                        else:
                            group.create_task(
                                self._copy_file(
                                    blobs,
                                    item,
                                    child,
                                    size=path.content_length,
                                    copies=copies,
                                    progress=progress,
                                )
                            )

            try:
                await folder(source.strip("/"), target.strip("/"))
            except BaseExceptionGroup as group:
                raise _first(group) from None

    async def _copy_file(
        self,
        blobs: BlobServiceClient,
        source: str,
        target: str,
        *,
        size: int | None,
        copies: asyncio.Semaphore,
        progress: Progress,
    ) -> None:
        """Copy one file with Copy Blob, polling until it ends; delete the
        target if it fails, is aborted or is cancelled."""
        name = _paths.basename(source)
        async with copies:
            progress.check()
            progress.working_on(name)
            source_blob = blobs.get_blob_client(*_split(source))
            target_blob = blobs.get_blob_client(*_split(target))
            # The source's URL carries the account's SAS token, if any.
            copy = await target_blob.start_copy_from_url(source_blob.url)
            status, description = copy.get("copy_status"), None
            try:
                for interval in _intervals(self.POLL_INTERVALS):
                    if status != "pending":
                        break
                    await asyncio.sleep(interval)
                    progress.check()
                    properties = await target_blob.get_blob_properties()
                    status = properties.copy.status
                    description = properties.copy.status_description
                if status in ("failed", "aborted"):
                    # Ended by the storage, or aborted by another client.
                    raise OSError(
                        f"{name}: copy {status}"
                        + (f" ({description})" if description else "")
                    )
                if status != "success":
                    raise OSError(f"{name}: unexpected copy status {status!r}")
            except BaseException:
                # Only a copy still pending can be aborted; one that ended
                # (failed or aborted) has only its target to delete.
                pending = status == "pending"
                await _discard(target_blob, copy.get("copy_id") if pending else None)
                raise
        progress.advance(files=1, bytes=size or 0)


def _blob_service_client(service: DataLakeServiceClient) -> BlobServiceClient:
    """A Blob Storage client of ``service``'s account: its URL (the Blob
    endpoint, "blob" for "dfs"; with its SAS token, if any) and credential."""
    url = service.url.replace(".dfs.", ".blob.", 1)
    return _azure().BlobServiceClient(url, credential=service.credential)


def _azure() -> ModuleType:
    """adlfs and the Azure SDK (``_azure.py``), imported on first use."""
    return importlib.import_module("jupyter_storage_explorer_abfs_support._azure")


def _intervals(intervals: tuple[float, ...]) -> Iterator[float]:
    """``intervals``, then the last one for ever."""
    yield from intervals
    while True:
        yield intervals[-1]


async def _discard(blob: Any, copy_id: str | None) -> None:
    """Abort ``blob``'s copy ``copy_id`` (one still pending), and delete
    what it wrote: best effort, as the copy may have ended meanwhile or
    written nothing."""
    if copy_id:
        with contextlib.suppress(Exception):  # ended meanwhile
            await blob.abort_copy(copy_id)
    with contextlib.suppress(Exception):  # nothing written
        await blob.delete_blob()


def _first(group: BaseExceptionGroup) -> BaseException:
    """The error to report from a group of tasks' errors: a cancel first,
    else the first error (TaskGroup wraps them all)."""
    errors = list(_leaves(group))
    for error in errors:
        if isinstance(error, OperationCancelled):
            return error
    return errors[0]


def _leaves(group: BaseExceptionGroup) -> Iterator[BaseException]:
    for error in group.exceptions:
        if isinstance(error, BaseExceptionGroup):
            yield from _leaves(error)
        else:
            yield error


def _split(path: str) -> tuple[str, str]:
    """("container", "key") of an adlfs path "container/key"."""
    container, _, key = path.strip("/").partition("/")
    return container, key.strip("/")
