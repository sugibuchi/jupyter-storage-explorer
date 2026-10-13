"""Locations (URLs) of paths on fsspec filesystems, as code and users use them,
and back: the filesystem and path of a location."""

from __future__ import annotations

import re
import urllib.parse
from typing import TYPE_CHECKING

import fsspec
from fsspec.core import url_to_fs
from fsspec.implementations.dirfs import DirFileSystem

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem

# "protocol://", but not a Windows drive ("C:\..." or "C:/...").
_PROTOCOL = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+)://")


def default_url(fs: AbstractFileSystem, path: str) -> str:
    """The location of ``path`` on ``fs``.

    A plain path for local files, which every library reads; for Azure
    (adlfs), ``abfs://container@account.dfs.core.windows.net/key``, which
    names the account; and ``protocol://path`` otherwise.
    """
    protocols = _protocols(fs)
    if "file" in protocols:
        return path
    if "abfs" in protocols and (url := _azure_url(fs, path)) is not None:
        return url
    return fs.unstrip_protocol(path)


def default_location(
    url: str, filesystems: Sequence[AbstractFileSystem]
) -> tuple[AbstractFileSystem, str]:
    """The filesystem and path of a location made by ``default_url``.

    The first of ``filesystems`` (an explorer's, the one shown first) with
    the URL's protocol is used, with its options and credentials; for Azure,
    the first of the URL's account. Otherwise fsspec opens one from the URL,
    with the environment's credentials. Plain paths are local files.

    URLs do not always tell the storage apart: an S3 URL does not name its
    endpoint, so ``s3://bucket/key`` is taken to be on the first S3
    filesystem. Azure URLs without the account (``abfs://container/key``)
    are refused rather than guessed, as are filesystems that wrap another
    (``DirFileSystem``), whose URLs do not say where they start.

    Raises ValueError for such URLs, and whatever fsspec raises when it
    cannot open one.
    """
    match = _PROTOCOL.match(url)
    protocol = match.group(1) if match else "file"
    if protocol in ("abfs", "abfss", "az"):
        return _azure_location(url, filesystems)
    if protocol == "dir":
        raise ValueError(
            f"{url}: the location of a folder in another storage is unknown"
        )
    for fs in filesystems:
        if protocol in _protocols(fs) and not isinstance(fs, DirFileSystem):
            return fs, fs._strip_protocol(url) or fs.root_marker
    return url_to_fs(url)


def _protocols(fs: AbstractFileSystem) -> tuple[str, ...]:
    return (fs.protocol,) if isinstance(fs.protocol, str) else tuple(fs.protocol)


def _azure_url(fs: AbstractFileSystem, path: str) -> str | None:
    """``abfs://container@account.dfs.core.windows.net/key`` for adlfs's
    "container/key", or None if the account's host is unknown.

    adlfs's own URLs ("abfs://container/key") leave the account out. The host
    comes from the filesystem's blob endpoint, so other Azure clouds keep
    their domain; emulators and custom endpoints get None.
    """
    host = _blob_host(fs)
    container, _, key = path.strip("/").partition("/")
    if not host or ".blob." not in host or not container:
        return None
    return f"abfs://{container}@{host.replace('.blob.', '.dfs.', 1)}/{key}"


def _azure_location(
    url: str, filesystems: Sequence[AbstractFileSystem]
) -> tuple[AbstractFileSystem, str]:
    """The reverse of ``_azure_url``: the filesystem of the URL's account
    among ``filesystems``, else a new one (adlfs, the environment's
    credentials), and "container/key"."""
    parts = urllib.parse.urlsplit(url)
    container, at, host = parts.netloc.partition("@")
    if not at or not container or ".dfs." not in host:
        raise ValueError(
            f"{url}: the storage account is unknown "
            f"(expected abfs://container@account.dfs.core.windows.net/...)"
        )
    path = f"{container}/{parts.path.strip('/')}".rstrip("/")
    blob_host = host.replace(".dfs.", ".blob.", 1)
    for fs in filesystems:
        if "abfs" in _protocols(fs) and _blob_host(fs) == blob_host:
            return fs, path
    account = host.split(".", 1)[0]
    return fsspec.filesystem("abfs", account_name=account, account_host=blob_host), path


def _blob_host(fs: AbstractFileSystem) -> str | None:
    """The host of an adlfs filesystem's blob endpoint, which names its
    account (e.g. "account.blob.core.windows.net")."""
    return urllib.parse.urlsplit(getattr(fs, "account_url", None) or "").hostname
