"""The predefined locations (see ``jupyter_storage_explorer.location``): Azure
Blob Storage and Data Lake Storage Gen2, Amazon S3 and S3-compatible stores,
Google Cloud Storage, SFTP servers, the local disk, fsspec's memory
filesystem, and fsspec's URLs for the filesystems no mapper knows. The
mappers of mappers.py make them."""

from __future__ import annotations

import dataclasses
import os
import urllib.parse
from typing import TYPE_CHECKING, Self

from jupyter_storage_explorer.location import Location, trim

if TYPE_CHECKING:
    from collections.abc import Hashable


def _set(location: Location, **values: object) -> None:
    """Set normalized fields of a frozen ``location`` in ``__post_init__``."""
    for name, value in values.items():
        object.__setattr__(location, name, value)


def origin(url: str) -> str:
    """``scheme://host[:port]`` of ``url``, in lower case: the same endpoint
    written two ways compares equal."""
    parts = urllib.parse.urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()


class _InContainer(Location):
    """A location whose path starts with a container or bucket: ``join``,
    ``parent`` and ``name`` see "container/path" as one path, so that the
    top of the storage holds the containers."""

    container_field = ""

    @property
    def _path(self) -> str:
        return f"{getattr(self, self.container_field)}/{getattr(self, self.path_field)}".strip(
            "/"
        )

    def _with_path(self, path: str) -> Self:
        container, _, rest = path.strip("/").partition("/")
        return dataclasses.replace(
            self, **{self.container_field: container, self.path_field: rest}
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class AbfsLocation(_InContainer):
    """A file or folder of an Azure storage account (Blob Storage, Data Lake
    Storage Gen2), as Hadoop and Spark name it:
    ``abfs://container@account.dfs.core.windows.net/path``, which adlfs reads
    too.

    Attributes
    ----------
    account_name : str
        The storage account, in lower case; unique within an Azure cloud.
    container_name : str
        The container (file system); empty at the top of the account.
    path : str
        The path within the container, without "/" at either end.
    endpoint_suffix : str or None, default "dfs.core.windows.net"
        The domain of the account's Data Lake endpoint, which other Azure
        clouds change. None for an emulator or another endpoint: the URL is
        then adlfs's own, ``abfs://container/path``, which does not name the
        account.
    """

    kind = "abfs"
    container_field = "container_name"

    account_name: str
    container_name: str = ""
    path: str = ""
    endpoint_suffix: str | None = "dfs.core.windows.net"

    def __post_init__(self) -> None:
        _set(
            self,
            account_name=self.account_name.lower(),
            path=self.path.strip("/"),
            endpoint_suffix=self.endpoint_suffix and self.endpoint_suffix.lower(),
        )

    @property
    def protocol(self) -> str:
        return "abfs"

    @property
    def url(self) -> str:
        if not self.container_name:
            return "abfs://"  # the account's containers, as adlfs lists them
        if self.endpoint_suffix is None:
            return f"abfs://{self.container_name}/{self.path}"
        host = f"{self.account_name}.{self.endpoint_suffix}"
        return f"abfs://{self.container_name}@{host}/{self.path}"

    @property
    def storage(self) -> Hashable:
        return ("abfs", self.account_name, self.endpoint_suffix)


@dataclasses.dataclass(frozen=True, kw_only=True)
class _BucketLocation(_InContainer):
    """``<protocol>://bucket/key``."""

    container_field = "bucket"
    path_field = "key"

    bucket: str = ""
    key: str = ""
    endpoint: str | None = None

    def __post_init__(self) -> None:
        _set(
            self,
            key=self.key.strip("/"),
            endpoint=self.endpoint and origin(self.endpoint),
        )

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self._path}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class S3Location(_BucketLocation):
    """An object or folder of Amazon S3 or an S3-compatible store:
    ``s3://bucket/key``.

    Attributes
    ----------
    bucket : str
        The bucket; empty at the top.
    key : str
        The object's key, without "/" at either end.
    endpoint : str or None
        The endpoint of an S3-compatible store, ``scheme://host[:port]`` in
        lower case (e.g. "http://minio:9000"); None for AWS. Not in the URL:
        libraries need it in their options.
    partition : str or None, default "aws"
        The AWS partition ("aws", "aws-cn", "aws-us-gov"), within which bucket
        names are unique; None with an endpoint.
    """

    kind = "s3"

    partition: str | None = "aws"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.endpoint:
            _set(self, partition=None)

    @property
    def protocol(self) -> str:
        return "s3"

    @property
    def storage(self) -> Hashable:
        return ("s3", self.endpoint or self.partition)


@dataclasses.dataclass(frozen=True, kw_only=True)
class GcsLocation(_BucketLocation):
    """An object or folder of Google Cloud Storage: ``gs://bucket/key``.

    Attributes
    ----------
    bucket : str
        The bucket; empty at the top. Bucket names are unique.
    key : str
        The object's key, without "/" at either end.
    endpoint : str or None
        An emulator's endpoint, ``scheme://host[:port]`` in lower case; None
        for Google's.
    """

    kind = "gs"

    @property
    def protocol(self) -> str:
        return "gs"

    @property
    def storage(self) -> Hashable:
        return ("gs", self.endpoint)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SftpLocation(Location):
    """A file or folder of an SFTP server: ``sftp://user@host:port/path``.

    A server may show each user a tree of their own (a chroot), so the user
    is part of the storage.

    Attributes
    ----------
    host : str
        The server, in lower case.
    port : int, default 22
    user : str or None
        The user name, if any.
    path : str
        The absolute path on the server.
    """

    kind = "sftp"

    host: str
    port: int = 22
    user: str | None = None
    path: str = "/"

    def __post_init__(self) -> None:
        _set(
            self,
            host=self.host.lower(),
            port=int(self.port),
            path="/" + self.path.strip("/"),
        )

    @property
    def protocol(self) -> str:
        return "sftp"

    @property
    def url(self) -> str:
        user = f"{self.user}@" if self.user else ""
        return f"sftp://{user}{self.host}:{self.port}{self.path}"

    @property
    def storage(self) -> Hashable:
        return ("sftp", self.host, self.port, self.user)


@dataclasses.dataclass(frozen=True, kw_only=True)
class LocalLocation(Location):
    """A file or folder of a machine's disk: ``file:///home/u/a.csv``,
    ``file:///C:/data/a.csv``.

    Attributes
    ----------
    path : str
        The absolute path as fsspec names it, with "/" between folders, also
        on Windows ("C:/data/a.csv"): what libraries reading local files
        take. ``os_path`` is the system's own form.
    hostname : str
        The machine, in lower case.
    machine_id : str or None
        The id the system gives the machine, where there is one: containers
        may share a hostname's machine, and machines a hostname.
    """

    kind = "file"

    path: str
    hostname: str
    machine_id: str | None = None

    def __post_init__(self) -> None:
        _set(self, path=trim(self.path), hostname=self.hostname.lower())

    @property
    def protocol(self) -> str:
        return "file"

    @property
    def url(self) -> str:
        return f"file://{'' if self.path.startswith('/') else '/'}{self.path}"

    @property
    def os_path(self) -> str:
        """The path in the system's form, e.g. "C:\\data\\a.csv" on Windows:
        what "Copy path" copies."""
        return os.path.normpath(self.path)

    @property
    def storage(self) -> Hashable:
        return ("file", self.hostname, self.machine_id)


@dataclasses.dataclass(frozen=True, kw_only=True)
class MemoryLocation(Location):
    """A file or folder of fsspec's memory filesystem of one process:
    ``memory:///dir/a.csv``. Other processes (kernels) cannot read it.

    Attributes
    ----------
    path : str
        The absolute path, as fsspec names it.
    process : str
        The process whose memory it is in (a random id).
    """

    kind = "memory"

    path: str
    process: str

    def __post_init__(self) -> None:
        _set(self, path="/" + self.path.strip("/"))

    @property
    def protocol(self) -> str:
        return "memory"

    @property
    def url(self) -> str:
        return f"memory://{self.path}"

    @property
    def storage(self) -> Hashable:
        return ("memory", self.process)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FsspecLocation(Location):
    """A file or folder of a filesystem no mapper knows: fsspec's URL.

    Nothing tells which storage such a URL is on, so explorers look for it
    only among their own storages of its protocol, and never open a
    filesystem from it.

    Attributes
    ----------
    fsspec_protocol : str
        fsspec's protocol, e.g. "ftp".
    fsspec_url : str
        fsspec's URL, ``fs.unstrip_protocol(path)``.
    """

    kind = "fsspec"

    fsspec_protocol: str
    fsspec_url: str

    @property
    def protocol(self) -> str:
        return self.fsspec_protocol

    @property
    def url(self) -> str:
        return self.fsspec_url

    @property
    def storage(self) -> Hashable:
        return ("fsspec", self.fsspec_protocol)

    @property
    def _path(self) -> str:
        return self.fsspec_url.partition("://")[2] or self.fsspec_url

    def _with_path(self, path: str) -> Self:
        prefix, sep, _ = self.fsspec_url.partition("://")
        return dataclasses.replace(
            self, fsspec_url=f"{prefix}{sep}{path}" if sep else path
        )
