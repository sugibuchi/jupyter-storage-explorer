"""The predefined filesystem mappers (see mapper.py): Azure Blob Storage and
Data Lake Storage Gen2 (adlfs), Amazon S3 and S3-compatible stores (s3fs),
Google Cloud Storage (gcsfs), the local disk, fsspec's memory filesystem, and
SFTP servers (fsspec's own, and sshfs). They match fsspec classes by name, so none of these packages is
imported. Their locations are in locations.py.
"""

from __future__ import annotations

import functools
import socket
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.filesystems.locations import (
    AbfsLocation,
    GcsLocation,
    LocalLocation,
    MemoryLocation,
    S3Location,
    SftpLocation,
    origin,
)
from jupyter_storage_explorer.filesystems.mapper import (
    FileSystemMapper,
    MapperChain,
)

if sys.platform == "win32":
    import winreg

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.location import Location


class AzureBlobMapper(FileSystemMapper):
    """adlfs's ``AzureBlobFileSystem``, which reaches the containers (the
    file systems, as Azure names them) of one storage account.

    Its locations are ``AbfsLocation``s of the account, whose URLs are those
    of Hadoop and Spark, ``abfs://container@acct.dfs.core.windows.net/key``,
    which name the account (adlfs's own, ``abfs://container/key``, do not).
    The domain comes from the filesystem's blob endpoint, so other Azure
    clouds keep theirs; with an emulator or a custom endpoint, URLs are
    adlfs's.
    """

    classes = ("adlfs.spec.AzureBlobFileSystem",)
    levels = ("account", "container")

    def to_location(self, fs: AbstractFileSystem, path: str) -> AbfsLocation:
        host = _blob_host(fs) or ""
        account = getattr(fs, "account_name", None) or host.split(".")[0]
        suffix = None
        if ".blob." in host:
            suffix = host.split(".", 1)[1].replace("blob.", "dfs.", 1)
        container, _, key = path.strip("/").partition("/")
        return AbfsLocation(
            account_name=account,
            container_name=container,
            path=key,
            endpoint_suffix=suffix,
        )

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches all the containers of its account (in its cloud).
        here = self.to_location(fs, "")
        if not isinstance(location, AbfsLocation) or (
            location.account_name,
            location.endpoint_suffix,
        ) != (here.account_name, here.endpoint_suffix):
            return None
        return f"{location.container_name}/{location.path}".strip("/")


def _blob_host(fs: AbstractFileSystem) -> str | None:
    """The host of an adlfs filesystem's blob endpoint, which names its
    account (e.g. "acct.blob.core.windows.net")."""
    return urllib.parse.urlsplit(getattr(fs, "account_url", None) or "").hostname


class S3Mapper(FileSystemMapper):
    """s3fs's ``S3FileSystem``, which reaches the buckets of one endpoint.

    Its locations are ``S3Location``s of its endpoint, when one is set
    (S3-compatible stores), else of its AWS partition (from the region set,
    if any), within which bucket names are unique. Their URLs,
    ``s3://bucket/key``, do not name an endpoint, so an S3-compatible store
    is reached from another kernel only if its explorer has it.
    """

    classes = ("s3fs.core.S3FileSystem",)
    # The top: the buckets of an endpoint or partition.
    levels = ("endpoint", "bucket")

    def to_location(self, fs: AbstractFileSystem, path: str) -> S3Location:
        bucket, _, key = path.strip("/").partition("/")
        client_kwargs = getattr(fs, "client_kwargs", None) or {}
        endpoint = getattr(fs, "endpoint_url", None) or client_kwargs.get(
            "endpoint_url"
        )
        if endpoint:
            return S3Location(bucket=bucket, key=key, endpoint=endpoint)
        region = client_kwargs.get("region_name") or ""
        partition = "aws"
        if region.startswith("cn-"):
            partition = "aws-cn"
        elif region.startswith("us-gov-"):
            partition = "aws-us-gov"
        return S3Location(bucket=bucket, key=key, partition=partition)

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches all the buckets of its endpoint (or partition).
        here = self.to_location(fs, "")
        if not isinstance(location, S3Location) or (
            location.endpoint,
            location.partition,
        ) != (here.endpoint, here.partition):
            return None
        return f"{location.bucket}/{location.key}".strip("/")


class GCSMapper(FileSystemMapper):
    """gcsfs's ``GCSFileSystem``. Bucket names are unique in Google Cloud
    Storage, so its locations, ``GcsLocation``s, have no endpoint, except
    with another one (an emulator)."""

    classes = ("gcsfs.core.GCSFileSystem",)
    levels = ("endpoint", "bucket")

    def to_location(self, fs: AbstractFileSystem, path: str) -> GcsLocation:
        bucket, _, key = path.strip("/").partition("/")
        endpoint = getattr(fs, "_endpoint", None) or ""
        if not endpoint or origin(endpoint) == "https://storage.googleapis.com":
            endpoint = None
        return GcsLocation(bucket=bucket, key=key, endpoint=endpoint)

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches all the buckets of its endpoint.
        here = self.to_location(fs, "")
        if not isinstance(location, GcsLocation) or location.endpoint != here.endpoint:
            return None
        return f"{location.bucket}/{location.key}".strip("/")


class LocalMapper(FileSystemMapper):
    """fsspec's ``LocalFileSystem``: the disk of the kernel's machine.

    Its locations, ``LocalLocation``s, name the machine, by its hostname and
    the id the system keeps, where there is one. Best effort: containers made
    from one image may share a machine id, so the hostname, a container's
    own, is part of it; and two machines sharing a volume are still two,
    their files copied rather than moved.
    """

    classes = ("fsspec.implementations.local.LocalFileSystem",)
    # A drive's top folder: "/", or on Windows "C:/" (one folder deep, as
    # the explorer counts: "C:" is its name).
    levels = ("", "drive") if sys.platform == "win32" else ("drive",)

    def to_location(self, fs: AbstractFileSystem, path: str) -> LocalLocation:
        return LocalLocation(path=path, **_machine())

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches its machine's disk.
        if not isinstance(location, LocalLocation):
            return None
        machine = _machine()
        if (location.hostname, location.machine_id) != (
            machine["hostname"],
            machine["machine_id"],
        ):
            return None
        return location.path


@functools.cache
def _machine() -> dict[str, Any]:
    """The machine, read once: it stays the same. {"hostname", "machine_id"}."""
    return {"hostname": socket.gethostname().lower(), "machine_id": _machine_id()}


def _machine_id() -> str | None:
    """The id the system gives the machine: systemd's or D-Bus's on Linux,
    Windows's MachineGuid; None elsewhere (e.g. macOS) or if unreadable."""
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0]).lower()
        except OSError:
            return None
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            if machine_id := Path(path).read_text(encoding="ascii").strip():
                return machine_id.lower()
        except (OSError, UnicodeDecodeError):
            continue
    return None


# This process, for memory filesystems: a pid could be another process's later.
_PROCESS = uuid.uuid4().hex


class MemoryMapper(FileSystemMapper):
    """fsspec's ``MemoryFileSystem``, whose files are shared by its instances
    in one process: its locations, ``MemoryLocation``s, name the process, so
    files copied in another kernel are never looked for in this one's memory."""

    classes = ("fsspec.implementations.memory.MemoryFileSystem",)
    levels = ("memory",)

    def to_location(self, fs: AbstractFileSystem, path: str) -> MemoryLocation:
        return MemoryLocation(path=path, process=_PROCESS)

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches its process's memory.
        if not isinstance(location, MemoryLocation) or location.process != _PROCESS:
            return None
        return location.path


class SFTPMapper(FileSystemMapper):
    """fsspec's ``SFTPFileSystem``. Its locations, ``SftpLocation``s, name the
    server's host and port and the user, as a server may show each user a
    tree of their own (a chroot)."""

    classes = ("fsspec.implementations.sftp.SFTPFileSystem",)
    levels = ("host",)

    def server(self, fs: AbstractFileSystem) -> dict[str, Any]:
        """{"host", "port", "user"} of ``fs``."""
        options = getattr(fs, "ssh_kwargs", None) or {}
        return {
            "host": str(fs.host),
            "port": int(options.get("port") or 22),
            "user": options.get("username"),
        }

    def to_location(self, fs: AbstractFileSystem, path: str) -> SftpLocation:
        return SftpLocation(path=path or "/", **self.server(fs))

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # An instance reaches its server's tree for its user.
        here = self.to_location(fs, "/")
        if not isinstance(location, SftpLocation) or (
            location.host,
            location.port,
            location.user,
        ) != (here.host, here.port, here.user):
            return None
        return location.path


class SSHFSMapper(SFTPMapper):
    """sshfs's ``SSHFileSystem`` (SFTP with asyncssh): the same locations as
    ``SFTPMapper``, so files copied from one are found on the other. It
    keeps no host or user of its own, so they are read from the arguments it
    was made with: the host (first, or ``host=``), ``port=`` and
    ``username=``."""

    classes = ("sshfs.spec.SSHFileSystem",)

    def server(self, fs: AbstractFileSystem) -> dict[str, Any]:
        args = getattr(fs, "storage_args", None) or ()
        options = getattr(fs, "storage_options", None) or {}
        host = args[0] if args else options.get("host", "")
        return {
            "host": str(host),
            "port": int(options.get("port") or 22),
            "user": options.get("username"),
        }


def default_mappers() -> list[FileSystemMapper]:
    """The mappers tried after an explorer's ``filesystem_mappers``.

    Returns
    -------
    list of FileSystemMapper
        New objects each time: ``AzureBlobMapper``, ``S3Mapper``,
        ``GCSMapper``, ``LocalMapper``, ``MemoryMapper``, ``SFTPMapper`` and
        ``SSHFSMapper``.
        Filesystems none of them maps get ``FsspecMapper``.
    """
    return [
        AzureBlobMapper(),
        S3Mapper(),
        GCSMapper(),
        LocalMapper(),
        MemoryMapper(),
        SFTPMapper(),
        SSHFSMapper(),
    ]


_DEFAULT = MapperChain(default_mappers())


def same_filesystem(a: AbstractFileSystem, b: AbstractFileSystem) -> bool:
    """Whether two filesystem objects take the same paths to the same files.

    They do if each reaches the other's top folder, as their mappers
    (``default_mappers()``) tell (``FileSystemMapper.path_of``: e.g. the same
    Azure account, S3 endpoint, or SFTP server and user), and for
    filesystems wrapped in ``DirFileSystem``s the same folders. Credentials are not part of it: the
    same storage opened with two of them is one filesystem, and an operation
    within it (e.g. a server-side move) uses the source's. Filesystems no
    mapper knows compare as fsspec compares them, by their class and
    arguments.

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
