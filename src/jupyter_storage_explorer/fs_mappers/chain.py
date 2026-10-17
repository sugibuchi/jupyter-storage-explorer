"""An explorer's mappers, and what it asks them: a filesystem's identity,
URLs and paths, where files copied in another kernel are, and whether two
filesystems are one (see base.py).

Filesystems that wrap another one in a folder (fsspec's ``DirFileSystem``)
are not mapped themselves: their paths are those of the filesystem they
wrap, under their folder, and their URLs its URLs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fsspec.core import url_to_fs
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.fs_mappers.azure import AzureBlobMapper
from jupyter_storage_explorer.fs_mappers.base import (
    FileSystemMapper,
    FsspecMapper,
    protocols,
)
from jupyter_storage_explorer.fs_mappers.local import LocalMapper, MemoryMapper
from jupyter_storage_explorer.fs_mappers.object_stores import GCSMapper, S3Mapper
from jupyter_storage_explorer.fs_mappers.sftp import SFTPMapper

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem

_FALLBACK = FsspecMapper()


def default_mappers() -> list[FileSystemMapper]:
    """The mappers tried after an explorer's ``filesystem_mappers``.

    Returns
    -------
    list of FileSystemMapper
        New objects each time: ``AzureBlobMapper``, ``S3Mapper``,
        ``GCSMapper``, ``LocalMapper``, ``MemoryMapper`` and ``SFTPMapper``.
        Filesystems none of them maps get ``FsspecMapper``.
    """
    return [
        AzureBlobMapper(),
        S3Mapper(),
        GCSMapper(),
        LocalMapper(),
        MemoryMapper(),
        SFTPMapper(),
    ]


class MapperChain:
    """Mappers tried in order: a filesystem's mapper is the first that
    ``matches`` it, else ``FsspecMapper``.

    Parameters
    ----------
    mappers : sequence of FileSystemMapper, optional
        Tried before ``default_mappers()``.
    """

    def __init__(self, mappers: Sequence[FileSystemMapper] = ()) -> None:
        self.mappers = [*mappers, *default_mappers()]

    def mapper_of(self, fs: AbstractFileSystem) -> FileSystemMapper:
        """The mapper of ``fs``, not a ``DirFileSystem``."""
        for mapper in self.mappers:
            if mapper.matches(fs):
                return mapper
        return _FALLBACK

    def storage_of(self, fs: AbstractFileSystem) -> dict[str, Any]:
        """What files of ``fs`` are sent with: ``{"protocol", "identifier"}``
        of the filesystem their URLs are in (for a ``DirFileSystem``, the one
        it wraps)."""
        inner, _ = _unwrap(fs)
        mapper = self.mapper_of(inner)
        return {
            "protocol": _protocol(mapper, inner),
            "identifier": mapper.identifier(inner),
        }

    def url_of(self, fs: AbstractFileSystem, path: str) -> str | None:
        """The URL of ``path`` of ``fs``, from the mapper of the filesystem
        it is in; None if it has none."""
        while isinstance(fs, DirFileSystem):
            path, fs = fs._join(path), fs.fs
        return self.mapper_of(fs).to_url(fs, path)

    def path_in(
        self,
        fs: AbstractFileSystem,
        protocol: str,
        identifier: dict[str, Any],
        url: str,
    ) -> str | None:
        """The path of ``url``, sent with ``protocol`` and ``identifier`` (see
        ``storage_of``), in ``fs``; None if ``fs`` does not reach it."""
        inner, folders = _unwrap(fs)
        mapper = self.mapper_of(inner)
        if _protocol(mapper, inner) != protocol or not mapper.accepts(
            inner, identifier
        ):
            return None
        path = mapper.path_of(inner, url)
        # Back out through the DirFileSystems, the innermost first.
        for folder in reversed(folders):
            if path is None or not (folder == "" or _paths.inside(path, folder)):
                return None
            path = path[len(folder) :].lstrip("/") if folder else path
        return path

    def locate(
        self,
        url: str,
        protocol: str,
        identifier: dict[str, Any],
        filesystems: Sequence[AbstractFileSystem],
    ) -> tuple[AbstractFileSystem, str]:
        """The filesystem and path of ``url``, sent from another kernel with
        ``protocol`` and ``identifier`` (see ``storage_of``).

        The first of ``filesystems`` (an explorer's, the one shown first)
        that reaches it, with its options and credentials; else one fsspec
        opens from the URL, with the environment's credentials, if it is that
        filesystem (its mapper gives the same identifier). So files on
        storages of the other kernel's own, its memory or another machine's
        disk, are never looked for in this one's.

        Raises ValueError if neither reaches it.
        """
        for fs in filesystems:
            if (path := self.path_in(fs, protocol, identifier, url)) is not None:
                return fs, path
        try:
            fs, _ = url_to_fs(url)
        except Exception as exc:
            raise ValueError(f"not reachable from this kernel ({exc})") from exc
        if (path := self.path_in(fs, protocol, identifier, url)) is not None:
            return fs, path
        raise ValueError("not reachable from this kernel")

    def same_filesystem(self, a: AbstractFileSystem, b: AbstractFileSystem) -> bool:
        """Whether ``a`` and ``b`` take the same paths to the same files (see
        ``same_filesystem``)."""
        if a is b or a == b:
            return True
        (inner_a, folders_a), (inner_b, folders_b) = _unwrap(a), _unwrap(b)
        if folders_a != folders_b:
            return False
        if _FALLBACK in (self.mapper_of(inner_a), self.mapper_of(inner_b)):
            return inner_a == inner_b
        return self.storage_of(inner_a) == self.storage_of(inner_b)


_DEFAULT = MapperChain()


def same_filesystem(a: AbstractFileSystem, b: AbstractFileSystem) -> bool:
    """Whether two filesystem objects take the same paths to the same files.

    They do if their mappers (``default_mappers()``) give them the same
    protocol and identifier (see ``FileSystemMapper``), and for filesystems
    wrapped in ``DirFileSystem``s the same folders. Credentials are not part
    of it: the same storage opened with two of them is one filesystem, and an
    operation within it (e.g. a server-side move) uses the source's.
    Filesystems no mapper knows compare as fsspec compares them, by their
    class and arguments.

    Parameters
    ----------
    a, b : AbstractFileSystem
        The filesystems to compare.

    Returns
    -------
    bool
        True if a path of one is the same file on the other.
    """
    return _DEFAULT.same_filesystem(a, b)


def _unwrap(fs: AbstractFileSystem) -> tuple[AbstractFileSystem, list[str]]:
    """The filesystem ``fs`` wraps (itself if none), and the folders of the
    ``DirFileSystem``s around it, the outermost first."""
    folders = []
    while isinstance(fs, DirFileSystem):
        folders.append(fs.path)
        fs = fs.fs
    return fs, folders


def _protocol(mapper: FileSystemMapper, fs: AbstractFileSystem) -> str:
    """The protocol files of ``fs`` are sent with: its mapper's, or for
    ``FsspecMapper``, fsspec's first one for it."""
    return mapper.protocol or protocols(fs)[0]
