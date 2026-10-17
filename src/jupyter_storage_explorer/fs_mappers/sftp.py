"""SFTP servers (fsspec's ``SFTPFileSystem``, with paramiko)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper, split_url

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


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
