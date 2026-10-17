"""Filesystem mappers: how explorers tell filesystems apart, and how their
paths become URLs and back (see base.py).

``FileSystemMapper`` (base.py) is the interface. An explorer tries its
``filesystem_mappers`` argument, then ``default_mappers()`` (chain.py):
``AzureBlobMapper`` (azure.py), ``S3Mapper`` and ``GCSMapper``
(object_stores.py), ``LocalMapper`` and ``MemoryMapper`` (local.py),
``SFTPMapper`` (sftp.py). Filesystems none of them maps get
``FsspecMapper``, fsspec's URLs.
"""

from __future__ import annotations

from jupyter_storage_explorer.fs_mappers.azure import AzureBlobMapper
from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper, FsspecMapper
from jupyter_storage_explorer.fs_mappers.chain import (
    MapperChain,
    default_mappers,
    same_filesystem,
)
from jupyter_storage_explorer.fs_mappers.local import LocalMapper, MemoryMapper
from jupyter_storage_explorer.fs_mappers.object_stores import GCSMapper, S3Mapper
from jupyter_storage_explorer.fs_mappers.sftp import SFTPMapper

__all__ = [
    "AzureBlobMapper",
    "FileSystemMapper",
    "FsspecMapper",
    "GCSMapper",
    "LocalMapper",
    "MapperChain",
    "MemoryMapper",
    "S3Mapper",
    "SFTPMapper",
    "default_mappers",
    "same_filesystem",
]
