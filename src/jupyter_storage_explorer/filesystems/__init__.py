"""Filesystems: where their files are (locations, made by mappers), and how
they move, copy, delete, upload and download files (operations).

``FileSystemMapper`` (mapper.py) and ``FileSystemOperations``
(operation.py) are the interfaces; locations.py has the predefined
locations (``Location`` subclasses), level_icons.py the CSS of folders'
icons (``level_icon_css``), and mappers.py and operations.py the predefined
ones, tried after an explorer's own (its ``filesystem_mappers``
and ``filesystem_operations`` arguments): ``default_mappers()`` and
``default_operations()``. The predefined classes are imported from their
modules. Operations and mappers for particular storages come with plugins,
e.g. ``AzureDataLakeGen2Operation`` with abfs-support
(``pip install "jupyter-storage-explorer[abfs]"``).
"""

from jupyter_storage_explorer.filesystems.level_icons import level_icon_css
from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper, MapperChain
from jupyter_storage_explorer.filesystems.mappers import (
    default_mappers,
    same_filesystem,
)
from jupyter_storage_explorer.filesystems.operation import (
    FileSystemOperations,
    Measurement,
    OperationCancelled,
    Progress,
)
from jupyter_storage_explorer.filesystems.operations import default_operations

__all__ = [
    "FileSystemMapper",
    "FileSystemOperations",
    "MapperChain",
    "Measurement",
    "OperationCancelled",
    "Progress",
    "default_mappers",
    "default_operations",
    "level_icon_css",
    "same_filesystem",
]
