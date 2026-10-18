"""How fsspec filesystems are told apart, and how their paths become URLs and back.

A storage service's file system (an Azure container, an S3 bucket, an SFTP
server's tree for one user) is not always what one fsspec instance reaches:
an adlfs instance reaches all the containers of an account, an s3fs one all
the buckets of an endpoint. So a ``FileSystemMapper`` describes instances,
one fsspec implementation each: its ``identifier``, what the instance
reaches, as JSON without credentials; ``to_url``, the canonical URL of a
path; and ``path_of``, the reverse.

Identifiers are defined per protocol, not per implementation: every mapper of
``"abfs"`` gives ``{"account_name": ...}``, so that files copied from one
implementation of a protocol are found again on another. Two instances with
equal identifiers take the same paths to the same files, whatever their
credentials, so ``same_filesystem`` compares them.

``MapperChain`` holds an explorer's mappers and asks them. Filesystems that
wrap another one in a folder (fsspec's ``DirFileSystem``) are not mapped
themselves: their paths are those of the filesystem they wrap, under their
folder, and their URLs its URLs. The predefined mappers are in mappers.py.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from fsspec.core import url_to_fs
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer import _paths

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem

# "protocol://", but not a Windows drive ("C:\..." or "C:/...").
_PROTOCOL = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+)://")


class FileSystemMapper:
    """The identity and URLs of one fsspec implementation's filesystems.

    Subclass it for a filesystem the defaults do not know, or know
    differently, and give an instance to ``StorageExplorer`` in
    ``filesystem_mappers``, tried before the defaults.

    Attributes
    ----------
    protocol : str
        The protocol whose identifiers it gives (e.g. ``"abfs"``), sent with
        files copied or dragged: an explorer finds them again with a mapper
        of the same protocol.
    classes : tuple of str
        The qualified names of the fsspec classes it maps, e.g.
        ``("adlfs.spec.AzureBlobFileSystem",)``, matched against the
        filesystem's classes and their bases, so that subclasses are mapped
        too and optional packages need not be imported.

    Examples
    --------
    >>> class MyMapper(FileSystemMapper):
    ...     protocol = "myfs"
    ...     classes = ("mypackage.MyFileSystem",)
    ...
    ...     def identifier(self, fs):
    ...         return {"server": fs.server}
    >>> StorageExplorer(fs=my_filesystem, filesystem_mappers=[MyMapper()])
    """

    protocol: str = ""
    classes: tuple[str, ...] = ()

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

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        """What ``fs`` reaches: equal identifiers mean that the same paths are
        the same files.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.

        Returns
        -------
        dict
            JSON values, normalized so that they compare equal (e.g. hosts in
            lower case). Never credentials: they are sent to the browser with
            files copied or dragged.
        """
        raise NotImplementedError

    def to_url(self, fs: AbstractFileSystem, path: str) -> str | None:
        """The URL of ``path``, as users and libraries use it: "Copy URL",
        ``folder_url``, "Python code", previews that read by URL, the
        transfer policy, and files copied or dragged to another explorer.

        One URL per file, which ``fsspec.url_to_fs`` opens as the same
        storage where it can: another kernel opens it so when none of its
        explorer's storages has the identifier.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.
        path : str
            A path of ``fs``, as fsspec lists it.

        Returns
        -------
        str or None
            By default fsspec's ``protocol://path``. None for items without a
            URL: they can still be browsed, uploaded to, downloaded and
            moved, but have no "Copy URL", preview, "Query data", "Python
            code" or "Edit", and are not pasted in another kernel.
        """
        return fs.unstrip_protocol(path)

    def path_of(self, fs: AbstractFileSystem, url: str) -> str | None:
        """The reverse of ``to_url``: the path of ``url`` in ``fs``.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``, whose identifier is the one
            ``url`` was sent with.
        url : str
            A URL made by ``to_url``, maybe in another kernel.

        Returns
        -------
        str or None
            The path, or None if this mapper does not read such URLs. By
            default fsspec's path, for URLs of one of the filesystem's protocols.
        """
        if _scheme(url) not in protocols(fs):
            return None
        return fs._strip_protocol(url) or fs.root_marker

    def accepts(self, fs: AbstractFileSystem, identifier: dict[str, Any]) -> bool:
        """Whether files sent with ``identifier`` are on ``fs``.

        Parameters
        ----------
        fs : AbstractFileSystem
            A filesystem this mapper ``matches``.
        identifier : dict
            The identifier the files were sent with, from a mapper of the
            same protocol.

        Returns
        -------
        bool
            By default, whether it is the identifier of ``fs``.
        """
        return self.identifier(fs) == identifier


class FsspecMapper(FileSystemMapper):
    """The mapper of filesystems no other one maps: fsspec's URLs.

    It knows nothing of what they reach, so it sends no identifier and
    accepts files of its protocol whatever their identifier, the first
    storage with the protocol taking them (as explorers did before
    mappers); and ``same_filesystem`` compares such filesystems as fsspec
    does, by their class and arguments.
    """

    def matches(self, fs: AbstractFileSystem) -> bool:
        return True

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        return {}

    def accepts(self, fs: AbstractFileSystem, identifier: dict[str, Any]) -> bool:
        return True


def protocols(fs: AbstractFileSystem) -> tuple[str, ...]:
    """fsspec's protocols of ``fs``, always a tuple."""
    return (fs.protocol,) if isinstance(fs.protocol, str) else tuple(fs.protocol)


def _scheme(url: str) -> str:
    """The protocol of ``url``: "file" for a plain path."""
    match = _PROTOCOL.match(url)
    return match.group(1) if match else "file"


def split_url(url: str) -> tuple[str, str, str]:
    """The protocol, host part and path of ``protocol://host/path``, as they
    are: unlike urllib, "#" and "?" in file names are kept in the path."""
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return scheme, host, slash + path


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

        Only for protocols a mapper knows: for others, nothing tells whether a
        filesystem opened from the URL is the one the files are on, so they
        are found among ``filesystems`` only, and the kernel never connects
        to wherever such a URL (e.g. one dropped from another web page)
        points.

        Raises ValueError if neither reaches it.
        """
        for fs in filesystems:
            if (path := self.path_in(fs, protocol, identifier, url)) is not None:
                return fs, path
        if not any(mapper.protocol == protocol for mapper in self.mappers):
            raise ValueError(
                f"not reachable from this kernel (no storage of the explorer's "
                f"is the {protocol!r} storage it is on)"
            )
        try:
            fs, _ = url_to_fs(url)
        except Exception as exc:
            raise ValueError(f"not reachable from this kernel ({exc})") from exc
        if (path := self.path_in(fs, protocol, identifier, url)) is not None:
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
        if _FALLBACK in (self.mapper_of(inner_a), self.mapper_of(inner_b)):
            return inner_a == inner_b
        return self.storage_of(inner_a) == self.storage_of(inner_b)


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
