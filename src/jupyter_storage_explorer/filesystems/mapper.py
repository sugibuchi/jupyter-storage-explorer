"""How fsspec filesystems' paths become locations, and back.

A storage service's file system (an Azure container, an S3 bucket, an SFTP
server's tree for one user) is not always what one fsspec instance reaches:
an adlfs instance reaches all the containers of an account, an s3fs one all
the buckets of an endpoint. So a ``FileSystemMapper`` describes instances,
one fsspec implementation each: ``to_location``, the location of a path
(``jupyter_storage_explorer.location``), and ``path_of``, the reverse, which
also tells whether the instance reaches a location at all, as only the
implementation knows what one instance reaches.

Locations are defined per kind of storage, not per implementation: every
mapper of an SFTP implementation gives ``SftpLocation``s, so that files
copied from one are found again on another. Two instances each reaching the
other's top folder take the same paths to the same files, whatever their
credentials, so ``same_filesystem`` asks that.

``MapperChain`` holds an explorer's mappers and asks them. Filesystems that
wrap another one in a folder (fsspec's ``DirFileSystem``) are not mapped
themselves: their paths are those of the filesystem they wrap, under their
folder, and their locations its locations. The predefined mappers are in
mappers.py, the predefined locations in locations.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fsspec.core import url_to_fs
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.filesystems.locations import FsspecLocation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.location import Location


class FileSystemMapper:
    """The locations of one fsspec implementation's files.

    Subclass it for a filesystem the defaults do not know, or know
    differently, and give an instance to ``StorageExplorer`` in
    ``filesystem_mappers``, tried before the defaults. Its locations are
    usually of a ``Location`` subclass of its own, whose fields say where
    they are; its ``path_of`` tells which of them an instance reaches.

    Attributes
    ----------
    classes : tuple of str
        The qualified names of the fsspec classes it maps, e.g.
        ``("adlfs.spec.AzureBlobFileSystem",)``, matched against the
        filesystem's classes and their bases, so that subclasses are mapped
        too and optional packages need not be imported.
    levels : tuple of str
        What the storage makes of the folders at each depth from the
        filesystem's top folder (its root, ""), when more than folders: e.g.
        ``("account", "container")`` for adlfs, whose top is an Azure account
        and its folders the containers; "" for a depth of plain folders, as
        are those below the last. Empty by default. What ``level`` gives,
        unless a subclass overrides it.

    Examples
    --------
    >>> @dataclasses.dataclass(frozen=True, kw_only=True)
    ... class MyLocation(Location):
    ...     kind = "myfs"
    ...     server: str
    ...     path: str
    ...     url = property(lambda self: f"myfs://{self.server}{self.path}")
    >>> class MyMapper(FileSystemMapper):
    ...     classes = ("mypackage.MyFileSystem",)
    ...
    ...     def to_location(self, fs, path):
    ...         return MyLocation(server=fs.server, path=path)
    ...
    ...     def path_of(self, fs, location):
    ...         # Only the server's files: what an instance reaches.
    ...         if isinstance(location, MyLocation) and location.server == fs.server:
    ...             return location.path
    ...         return None
    >>> StorageExplorer(fs=my_filesystem, filesystem_mappers=[MyMapper()])
    """

    classes: tuple[str, ...] = ()
    levels: tuple[str, ...] = ()

    def matches(self, fs: AbstractFileSystem) -> bool:
        """Whether this mapper maps ``fs``.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem, never a ``DirFileSystem`` (see the module).

        Returns
        -------
        bool
            Whether one of ``classes`` is the class of ``fs`` or one of its bases.
        """
        return any(
            f"{cls.__module__}.{cls.__qualname__}" in self.classes
            for cls in type(fs).__mro__
        )

    def to_location(self, fs: AbstractFileSystem, path: str) -> Location | None:
        """The location of ``path``, as users and libraries use it: "Copy
        URL", ``folder_location``, "Python code", previews that read by URL,
        the transfer policy, and files copied or dragged to another explorer.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.
        path : str
            A path of ``fs``, as fsspec lists it; "" for its top folder.

        Returns
        -------
        Location or None
            By default fsspec's URL (``FsspecLocation``). None for items
            without a location: they can still be browsed, uploaded to,
            downloaded and moved, but have no "Copy URL", preview, "Query
            data", "Python code" or "Edit", and are not pasted in another
            kernel.
        """
        return FsspecLocation(url=fs.unstrip_protocol(path))

    def level(self, fs: AbstractFileSystem, path: str) -> str | None:
        """What the storage makes of the folder at ``path``, if more than a
        folder: e.g. "container" for an Azure container, "catalog" for a
        Unity Catalog's folder of Databricks volumes. The explorer gives such
        folders an icon of their own (for the predefined levels), and CSS
        selects them by it (``[data-fs-level]``).

        Called for every folder listed, so it must be quick: from the path
        and the instance's settings, never by reading the storage.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.
        path : str
            A folder of ``fs``, as fsspec lists it; "" or "/" for its top folder.

        Returns
        -------
        str or None
            By default ``levels`` by the folder's depth from the top folder;
            None for a plain folder. Override it when the level depends on
            the path, not only on its depth.
        """
        depth = len([part for part in path.split("/") if part])
        return (self.levels[depth] if depth < len(self.levels) else "") or None

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        """The reverse of ``to_location``: the path of ``location`` in ``fs``,
        if ``fs`` reaches it.

        What an instance reaches depends on the implementation (adlfs reaches
        all the containers of an account, Azure has a file system per
        container), so mappers tell it here, from the location's fields and
        the instance's settings, e.g. the account or the SFTP server and user.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.
        location : Location
            A location made by a mapper, maybe in another kernel.

        Returns
        -------
        str or None
            The path, or None if ``fs`` does not reach it. By default
            fsspec's path, for fsspec's URLs of one of the filesystem's
            protocols.
        """
        if not isinstance(location, FsspecLocation):
            return None
        if location.protocol not in protocols(fs):
            return None
        return fs._strip_protocol(location.url) or fs.root_marker


class FsspecMapper(FileSystemMapper):
    """The mapper of filesystems no other one maps: fsspec's URLs
    (``FsspecLocation``).

    It knows nothing of what they reach, so files of its protocol are
    taken by the first storage with the protocol (as explorers did before
    mappers); and ``same_filesystem`` compares such filesystems as fsspec
    does, by their class and arguments.
    """

    def matches(self, fs: AbstractFileSystem) -> bool:
        return True


def protocols(fs: AbstractFileSystem) -> tuple[str, ...]:
    """fsspec's protocols of ``fs``, always a tuple."""
    return (fs.protocol,) if isinstance(fs.protocol, str) else tuple(fs.protocol)


_FALLBACK = FsspecMapper()


class MapperChain:
    """Mappers tried in order: a filesystem's mapper is the first that
    ``matches`` it, else ``FsspecMapper``.

    Parameters
    ----------
    mappers : sequence of FileSystemMapper
        The mappers, in order: an explorer's are its ``filesystem_mappers``
        then ``default_mappers()``.
    """

    def __init__(self, mappers: Sequence[FileSystemMapper]) -> None:
        self.mappers = list(mappers)

    def mapper_of(self, fs: AbstractFileSystem) -> FileSystemMapper:
        """The mapper of ``fs``, not a ``DirFileSystem``."""
        for mapper in self.mappers:
            if mapper.matches(fs):
                return mapper
        return _FALLBACK

    def location_of(self, fs: AbstractFileSystem, path: str) -> Location | None:
        """The location of ``path`` of ``fs``, from the mapper of the
        filesystem it is in; None if it has none."""
        while isinstance(fs, DirFileSystem):
            path, fs = fs._join(path), fs.fs
        return self.mapper_of(fs).to_location(fs, path)

    def level_of(self, fs: AbstractFileSystem, path: str) -> str | None:
        """The level of folder ``path`` of ``fs`` (``FileSystemMapper.level``),
        from the mapper of the filesystem it is in: a ``DirFileSystem``'s
        folders are those of the filesystem it wraps."""
        while isinstance(fs, DirFileSystem):
            path, fs = fs._join(path), fs.fs
        return self.mapper_of(fs).level(fs, path)

    def path_in(self, fs: AbstractFileSystem, location: Location) -> str | None:
        """The path of ``location`` in ``fs``; None if ``fs`` does not reach it."""
        inner, folders = _unwrap(fs)
        path = self.mapper_of(inner).path_of(inner, location)
        # Back out through the DirFileSystems, the innermost first.
        for folder in reversed(folders):
            if path is None or not (folder == "" or _paths.inside(path, folder)):
                return None
            path = path[len(folder) :].lstrip("/") if folder else path
        return path

    def locate(
        self, location: Location, filesystems: Sequence[AbstractFileSystem]
    ) -> tuple[AbstractFileSystem, str]:
        """The filesystem and path of ``location``, sent from another kernel.

        The first of ``filesystems`` (an explorer's, the one shown first)
        that reaches it, with its options and credentials; else one fsspec
        opens from its URL, with the environment's credentials, if that one
        reaches it (as its mapper's ``path_of`` tells). So files on
        storages of the other kernel's own, its memory or another machine's
        disk, are never looked for in this one's.

        Not for fsspec's URLs (``FsspecLocation``): nothing tells whether a
        filesystem opened from one is the one the files are on, so they are
        found among ``filesystems`` only, and the kernel never connects to
        wherever such a URL points.

        Raises ValueError if neither reaches it.
        """
        for fs in filesystems:
            if (path := self.path_in(fs, location)) is not None:
                return fs, path
        if isinstance(location, FsspecLocation):
            raise ValueError(
                f"not reachable from this kernel (no storage of the explorer's "
                f"is the {location.protocol!r} storage it is on)"
            )
        try:
            fs, _ = url_to_fs(location.url)
        except Exception as exc:
            raise ValueError(f"not reachable from this kernel ({exc})") from exc
        if (path := self.path_in(fs, location)) is not None:
            return fs, path
        raise ValueError("not reachable from this kernel")

    def same_filesystem(self, a: AbstractFileSystem, b: AbstractFileSystem) -> bool:
        """Whether ``a`` and ``b`` take the same paths to the same files (see
        ``mappers.same_filesystem``)."""
        if a is b or a == b:
            return True
        (inner_a, folders_a), (inner_b, folders_b) = _unwrap(a), _unwrap(b)
        if folders_a != folders_b:
            return False
        mapper_a, mapper_b = self.mapper_of(inner_a), self.mapper_of(inner_b)
        top_a, top_b = (
            mapper_a.to_location(inner_a, ""),
            mapper_b.to_location(inner_b, ""),
        )
        # Mappers of fsspec's URLs (FsspecMapper and its subclasses) know
        # nothing of what instances reach.
        unknown = isinstance(mapper_a, FsspecMapper) or isinstance(
            mapper_b, FsspecMapper
        )
        if unknown or top_a is None or top_b is None:
            return inner_a == inner_b
        # Each reaches the other's top folder, as its own mapper tells.
        return (
            mapper_b.path_of(inner_b, top_a) is not None
            and mapper_a.path_of(inner_a, top_b) is not None
        )


def _unwrap(fs: AbstractFileSystem) -> tuple[AbstractFileSystem, list[str]]:
    """The filesystem ``fs`` wraps (itself if none), and the folders of the
    ``DirFileSystem``s around it, the outermost first."""
    folders = []
    while isinstance(fs, DirFileSystem):
        folders.append(fs.path)
        fs = fs.fs
    return fs, folders
