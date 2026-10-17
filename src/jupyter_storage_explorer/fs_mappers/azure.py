"""Azure Blob Storage and Data Lake Storage Gen2 (adlfs)."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper, split_url

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
