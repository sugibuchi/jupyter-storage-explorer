"""File operations with fsspec's synchronous API, for any filesystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.fs_operations._common import (
    measure_by_folder,
    measure_file,
    measure_found,
    prepare_folder_copy,
    remove_emptied_folder,
)
from jupyter_storage_explorer.fs_operations.base import (
    FileSystemOperations,
    same_filesystem,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.fs_operations.base import Measurement, Progress


class FsspecOperations(FileSystemOperations):
    """Every operation, with fsspec's API: works on any filesystem.

    Folders are moved, copied and deleted file by file (deletions in
    batches), so progress shows and a cancel takes effect between files.
    Within a filesystem, each file is moved with its ``mv`` (a rename where
    the storage has one; a copy then a delete on object stores) and copied
    with its ``cp_file``. Between filesystems, files go through ``_copy_file``
    and ``_move_file`` (by default, through local temporary files), so a
    cancel leaves each file in one place.
    """

    # Files deleted per request when deleting a folder: object stores delete
    # many files in one request, and cancelling takes effect between batches.
    DELETE_BATCH = 100

    def measure(
        self, fs: AbstractFileSystem, path: str, progress: Progress | None = None
    ) -> Measurement:
        """One recursive listing (``find``); with ``progress``, one ``ls`` per
        folder, so that it shows and can be cancelled."""
        info = fs.info(path)
        if info.get("type") != "directory":
            return measure_file(info, progress)
        if progress is None:
            return measure_found(path, fs.find(path, withdirs=True, detail=True))

        def list_folders(paths: Sequence[str]) -> list[Any]:
            try:
                return [fs.ls(paths[0], detail=True)]
            except Exception as exc:
                return [exc]

        return measure_by_folder(path, list_folders, progress)

    def move(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        same = same_filesystem(source_fs, target_fs)

        def move_file(path: str, dest: str) -> None:
            if same:
                source_fs.mv(path, dest)
            else:
                self._move_file(source_fs, path, target_fs, dest, progress)

        if not source_fs.isdir(source):
            progress.working_on(_paths.basename(source))
            move_file(source, target)
            return
        for path, dest, size in prepare_folder_copy(
            source_fs, source, target_fs, target
        ):
            progress.check()
            progress.working_on(_paths.basename(path))
            move_file(path, dest)
            # Transfers between filesystems report their bytes as they go.
            progress.advance(files=1, bytes=size if same else 0)
        remove_emptied_folder(source_fs, source)

    def copy(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        same = same_filesystem(source_fs, target_fs)

        def copy_file(path: str, dest: str) -> None:
            if same:
                source_fs.cp_file(path, dest)
            else:
                self._copy_file(source_fs, path, target_fs, dest, progress)

        if not source_fs.isdir(source):
            progress.working_on(_paths.basename(source))
            copy_file(source, target)
            return
        for path, dest, size in prepare_folder_copy(
            source_fs, source, target_fs, target
        ):
            progress.check()
            progress.working_on(_paths.basename(path))
            copy_file(path, dest)
            progress.advance(files=1, bytes=size if same else 0)

    def delete(self, fs: AbstractFileSystem, path: str, progress: Progress) -> None:
        if not fs.isdir(path):
            progress.working_on(_paths.basename(path))
            fs.rm_file(path)
            return
        files = fs.find(path, detail=True)
        names = list(files)
        for start in range(0, len(names), self.DELETE_BATCH):
            progress.check()
            batch = names[start : start + self.DELETE_BATCH]
            progress.working_on(_paths.basename(batch[-1]))
            fs.rm(batch)
            progress.advance(
                files=len(batch), bytes=sum(files[n].get("size") or 0 for n in batch)
            )
        # The folders left, e.g. on local disks.
        if fs.exists(path):
            fs.rm(path, recursive=True)

    def download(
        self, fs: AbstractFileSystem, path: str, local_path: str, progress: Progress
    ) -> None:
        progress.working_on(_paths.basename(path))
        fs.get_file(path, local_path, callback=progress.callback())

    def upload(
        self, local_path: str, fs: AbstractFileSystem, path: str, progress: Progress
    ) -> None:
        progress.working_on(_paths.basename(path))
        fs.put_file(local_path, path, callback=progress.callback())

    def mkdir(self, fs: AbstractFileSystem, path: str) -> None:
        fs.makedirs(path, exist_ok=False)


class AtomicMoveOperation(FileSystemOperations):
    """Moves within a filesystem whose own ``mv`` moves a folder in one step,
    e.g. a rename on a local disk: quicker than file by file, and never left
    half done, though its progress then shows no file until the end.

    Only ``move``, within one filesystem of ``protocols`` (or a
    ``DirFileSystem`` over one); everything else raises
    ``FileSystemOperations.NotSupported``, for the next operations object.

    Parameters
    ----------
    protocols : iterable of str, default ("file", "local", "memory")
        The protocols of the filesystems to move with their ``mv``. Add only
        those whose ``mv`` renames folders, e.g. ``"sftp"`` or ``"hdfs"``,
        not object stores, whose ``mv`` copies then deletes every file.

    Examples
    --------
    >>> StorageExplorer(
    ...     filesystems={...},
    ...     operations=[
    ...         AtomicMoveOperation([*AtomicMoveOperation.PROTOCOLS, "sftp"]),
    ...         AsyncFsspecOperations(),
    ...         FsspecOperations(),
    ...     ],
    ... )
    """

    PROTOCOLS = ("file", "local", "memory")

    def __init__(self, protocols: Iterable[str] = PROTOCOLS) -> None:
        self.protocols = frozenset(protocols)

    def move(
        self,
        source_fs: AbstractFileSystem,
        source: str,
        target_fs: AbstractFileSystem,
        target: str,
        progress: Progress,
    ) -> None:
        if not same_filesystem(source_fs, target_fs) or not self._renames(source_fs):
            raise self.NotSupported
        progress.working_on(_paths.basename(source))
        source_fs.mv(source, target, recursive=source_fs.isdir(source))

    def _renames(self, fs: AbstractFileSystem) -> bool:
        """Whether ``fs`` is one of ``protocols``, itself or under a DirFileSystem."""
        if isinstance(fs, DirFileSystem):
            return self._renames(fs.fs)
        protocols = (fs.protocol,) if isinstance(fs.protocol, str) else fs.protocol
        return not self.protocols.isdisjoint(protocols)
