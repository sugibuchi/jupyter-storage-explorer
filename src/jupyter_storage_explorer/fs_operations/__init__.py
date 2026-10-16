"""File operations: how ``StorageExplorer`` moves, copies, deletes, uploads
and downloads files, measures them and creates folders.

``FileSystemOperations`` (base.py) is the interface, with the ``Progress``
operations report to; ``StorageExplorer`` calls a chain of such objects (its
``operations`` argument, then ``StorageExplorer.default_operations()``):
``AtomicMoveOperation`` and ``FsspecOperations`` (fsspec.py), and
``AsyncFsspecOperations`` (async_fsspec.py). ``AzureDataLakeGen2Operation``
(abfs.py) is opt-in, as it needs the "abfs" extra: import it from
``jupyter_storage_explorer.fs_operations.abfs``.
"""

from jupyter_storage_explorer.fs_operations.async_fsspec import AsyncFsspecOperations
from jupyter_storage_explorer.fs_operations.base import (
    FileSystemOperations,
    Measurement,
    OperationCancelled,
    OperationChain,
    Progress,
    same_filesystem,
)
from jupyter_storage_explorer.fs_operations.fsspec import (
    AtomicMoveOperation,
    FsspecOperations,
)

__all__ = [
    "AsyncFsspecOperations",
    "AtomicMoveOperation",
    "FileSystemOperations",
    "FsspecOperations",
    "Measurement",
    "OperationCancelled",
    "OperationChain",
    "Progress",
    "same_filesystem",
]
