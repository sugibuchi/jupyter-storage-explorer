"""The predefined filesystem mappers (see mapper.py): Azure Blob Storage and
Data Lake Storage Gen2 (adlfs), Amazon S3 and S3-compatible stores (s3fs),
Google Cloud Storage (gcsfs), the local disk, fsspec's memory filesystem, and
SFTP servers (fsspec's own, and sshfs). They match fsspec classes by name, so none of these packages is
imported.
"""

from __future__ import annotations

import functools
import socket
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.filesystems.mapper import (
    FileSystemMapper,
    MapperChain,
    split_url,
)

if sys.platform == "win32":
    import winreg

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


class AzureBlobMapper(FileSystemMapper):
    """adlfs's ``AzureBlobFileSystem``, which reaches the containers (the
    file systems, as Azure names them) of one storage account.

    Its identifier is the account's name, ``{"account_name": "acct"}``;
    names are unique within an Azure cloud. URLs are those of Hadoop and
    Spark, ``abfs://container@acct.dfs.core.windows.net/key``, which name
    the account (adlfs's own, ``abfs://container/key``, do not; they are
    read too, as files come with their account's identifier). The host
    comes from the filesystem's blob endpoint, so other Azure clouds keep
    their domain; with an emulator or a custom endpoint, URLs are adlfs's.
    """

    protocol = "abfs"
    classes = ("adlfs.spec.AzureBlobFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        name = getattr(fs, "account_name", None) or (_blob_host(fs) or "").split(".")[0]
        return {"account_name": name.lower()}

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        host = _blob_host(fs)
        container, _, key = path.strip("/").partition("/")
        if not host or ".blob." not in host or not container:
            return fs.unstrip_protocol(path)
        return f"abfs://{container}@{host.replace('.blob.', '.dfs.', 1)}/{key}"

    def path_of(self, fs: AbstractFileSystem, url: str) -> str | None:
        scheme, netloc, path = split_url(url)
        if scheme not in ("abfs", "abfss", "az"):
            return None
        container, at, host = netloc.partition("@")
        if at and host.split(".")[0].lower() != self.identifier(fs)["account_name"]:
            return None  # another account's
        return f"{container}/{path.strip('/')}".strip("/")


def _blob_host(fs: AbstractFileSystem) -> str | None:
    """The host of an adlfs filesystem's blob endpoint, which names its
    account (e.g. "acct.blob.core.windows.net")."""
    return urllib.parse.urlsplit(getattr(fs, "account_url", None) or "").hostname


class _BucketMapper(FileSystemMapper):
    """Paths are "bucket/key", URLs ``<scheme>://bucket/key`` for each of
    ``schemes``, the first one made."""

    schemes: tuple[str, ...] = ()

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        return f"{self.schemes[0]}://{path.lstrip('/')}"

    def path_of(self, fs: AbstractFileSystem, url: str) -> str | None:
        scheme, bucket, key = split_url(url)
        if scheme not in self.schemes:
            return None
        return f"{bucket}/{key.strip('/')}".strip("/")


class S3Mapper(_BucketMapper):
    """s3fs's ``S3FileSystem``, which reaches the buckets of one endpoint.

    Its identifier is the endpoint, ``{"endpoint": "http://minio:9000"}``,
    when one is set (S3-compatible stores), else the AWS partition, e.g.
    ``{"partition": "aws"}``, within which bucket names are unique (from
    the region set, if any). URLs are ``s3://bucket/key``; ``s3a://`` (Spark's)
    are read too. They do not name an endpoint, so an S3-compatible store
    is reached from another kernel only if its explorer has it.
    """

    protocol = "s3"
    classes = ("s3fs.core.S3FileSystem",)
    schemes = ("s3", "s3a")

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        client_kwargs = getattr(fs, "client_kwargs", None) or {}
        endpoint = getattr(fs, "endpoint_url", None) or client_kwargs.get(
            "endpoint_url"
        )
        if endpoint:
            return {"endpoint": _origin(endpoint)}
        region = client_kwargs.get("region_name") or ""
        if region.startswith("cn-"):
            return {"partition": "aws-cn"}
        if region.startswith("us-gov-"):
            return {"partition": "aws-us-gov"}
        return {"partition": "aws"}


class GCSMapper(_BucketMapper):
    """gcsfs's ``GCSFileSystem``. Bucket names are unique in Google Cloud
    Storage, so its identifier is empty, ``{}``, except with another
    endpoint (an emulator): ``{"endpoint": ...}``. URLs are ``gs://bucket/key``;
    ``gcs://`` are read too."""

    protocol = "gs"
    classes = ("gcsfs.core.GCSFileSystem",)
    schemes = ("gs", "gcs")

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        endpoint = getattr(fs, "_endpoint", None) or ""
        if not endpoint or _origin(endpoint) == "https://storage.googleapis.com":
            return {}
        return {"endpoint": _origin(endpoint)}


def _origin(url: str) -> str:
    """``scheme://host[:port]`` of ``url``, in lower case: the same endpoint
    written two ways compares equal."""
    parts = urllib.parse.urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()


class LocalMapper(FileSystemMapper):
    """fsspec's ``LocalFileSystem``: the disk of the kernel's machine.

    Its identifier is the machine, ``{"hostname", "machine_id"}`` (the id
    the system keeps, where there is one). Best effort: containers made from
    one image may share a machine id, so the hostname, a container's own,
    is part of it; and two machines sharing a volume are still two, their
    files copied rather than moved. URLs are plain paths, which every
    library reads.
    """

    protocol = "file"
    classes = ("fsspec.implementations.local.LocalFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        return _machine()

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        return path


@functools.cache
def _machine() -> dict[str, Any]:
    """``LocalMapper``'s identifier, read once: the machine stays the same."""
    machine = {"hostname": socket.gethostname().lower()}
    if (machine_id := _machine_id()) is not None:
        machine["machine_id"] = machine_id
    return machine


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
    in one process: its identifier is the process, ``{"process": ...}``, so
    files copied in another kernel are never looked for in this one's memory."""

    protocol = "memory"
    classes = ("fsspec.implementations.memory.MemoryFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        return {"process": _PROCESS}


class SFTPMapper(FileSystemMapper):
    """fsspec's ``SFTPFileSystem``. A server may show each user a tree of
    their own (a chroot), so its identifier is ``{"host", "port", "user"}``,
    and URLs name all three: ``sftp://user@host:22/path``."""

    protocol = "sftp"
    classes = ("fsspec.implementations.sftp.SFTPFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        options = getattr(fs, "ssh_kwargs", None) or {}
        return {
            "host": str(fs.host).lower(),
            "port": int(options.get("port") or 22),
            "user": options.get("username"),
        }

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        server = self.identifier(fs)
        user = f"{server['user']}@" if server["user"] else ""
        return f"sftp://{user}{server['host']}:{server['port']}/{path.lstrip('/')}"

    def path_of(self, fs: AbstractFileSystem, url: str) -> str | None:
        scheme, _, path = split_url(url)
        if scheme not in ("sftp", "ssh"):
            return None
        return path or "/"


class SSHFSMapper(SFTPMapper):
    """sshfs's ``SSHFileSystem`` (SFTP with asyncssh): the same identifiers
    and URLs as ``SFTPMapper``, so files copied from one are found on the
    other. It keeps no host or user of its own, so they are read from the
    arguments it was made with: the host (first, or ``host=``), ``port=``
    and ``username=``."""

    classes = ("sshfs.spec.SSHFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        args = getattr(fs, "storage_args", None) or ()
        options = getattr(fs, "storage_options", None) or {}
        host = args[0] if args else options.get("host", "")
        return {
            "host": str(host).lower(),
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
