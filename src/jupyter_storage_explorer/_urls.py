"""Locations (URLs) of paths on fsspec filesystems, as code and users use them."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


def default_url(fs: AbstractFileSystem, path: str) -> str:
    """The location of ``path`` on ``fs``.

    A plain path for local files, which every library reads; for Azure
    (adlfs), ``abfs://container@account.dfs.core.windows.net/key``, which
    names the account; and ``protocol://path`` otherwise.
    """
    protocols = (fs.protocol,) if isinstance(fs.protocol, str) else fs.protocol
    if "file" in protocols:
        return path
    if "abfs" in protocols and (url := _azure_url(fs, path)) is not None:
        return url
    return fs.unstrip_protocol(path)


def _azure_url(fs: AbstractFileSystem, path: str) -> str | None:
    """``abfs://container@account.dfs.core.windows.net/key`` for adlfs's
    "container/key", or None if the account's host is unknown.

    adlfs's own URLs ("abfs://container/key") leave the account out. The host
    comes from the filesystem's blob endpoint, so other Azure clouds keep
    their domain; emulators and custom endpoints get None.
    """
    host = urllib.parse.urlsplit(getattr(fs, "account_url", None) or "").hostname
    container, _, key = path.strip("/").partition("/")
    if not host or ".blob." not in host or not container:
        return None
    return f"abfs://{container}@{host.replace('.blob.', '.dfs.', 1)}/{key}"
