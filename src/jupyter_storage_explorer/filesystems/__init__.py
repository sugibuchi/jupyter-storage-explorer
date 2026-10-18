"""Filesystems: how explorers tell them apart and name their files (mappers),
and how they move, copy, delete, upload and download files (operations).

``FileSystemMapper`` (mapper.py) and ``FileSystemOperations``
(operation.py) are the interfaces; mappers.py and operations.py have the
predefined ones, tried after an explorer's own (its ``filesystem_mappers``
and ``operations`` arguments): ``default_mappers()`` and
``default_operations()``. ``AzureDataLakeGen2Operation`` (abfs.py) is
opt-in, as it needs the "abfs" extra: import it from
``jupyter_storage_explorer.filesystems.abfs``.
"""

from jupyter_storage_explorer.filesystems.mapper import (
    FileSystemMapper,
    FsspecMapper,
    MapperChain,
)
from jupyter_storage_explorer.filesystems.mappers import (
    AzureBlobMapper,
    GCSMapper,
    LocalMapper,
    MemoryMapper,
    S3Mapper,
    SFTPMapper,
    default_mappers,
    same_filesystem,
)
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    Measurement,
    OperationCancelled,
    OperationChain,
    Progress,
    within_one_filesystem,
)
from jupyter_storage_explorer.filesystems.operations import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
    default_operations,
)

__all__ = [
    "AsyncFsspecOperations",
    "AtomicMoveOperation",
    "AzureBlobMapper",
    "FileSystemMapper",
    "FileSystemOperations",
    "FsspecMapper",
    "FsspecOperations",
    "GCSMapper",
    "LocalMapper",
    "MapperChain",
    "Measurement",
    "MemoryMapper",
    "OperationCancelled",
    "OperationChain",
    "Progress",
    "S3Mapper",
    "SFTPMapper",
    "default_mappers",
    "default_operations",
    "same_filesystem",
    "within_one_filesystem",
]
