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

Which mapper maps a filesystem, and what explorers ask them, is in chain.py.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
