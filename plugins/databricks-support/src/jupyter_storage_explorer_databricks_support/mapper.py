"""Locations of a Databricks workspace's files that name the workspace.

The explorer's own ``DatabricksMapper`` gives fsspec's URLs,
``dbfs://Volumes/...``, which do not tell the workspace: two workspaces' files
of the same path look the same, and files copied from another kernel are
looked for among the explorer's storages only. This mapper gives
fsspec-databricks' filesystems ``DatabricksLocation``s, with the workspace's
host, so that each is told apart, and found again from another kernel.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems import DatabricksMapper, FileSystemMapper

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class DatabricksLocation(Location):
    """A file or folder of a Databricks workspace: a Unity Catalog volume's,
    workspace files or legacy DBFS (``dbfs://Volumes/...``).

    Attributes
    ----------
    host : str
        The workspace's host name, in lower case, e.g.
        "adb-1234567890123456.7.azuredatabricks.net". Not in the URL, which
        libraries read as they read fsspec's: it tells the workspace apart.
    path : str
        The path in the workspace, from "/", e.g. "/Volumes/main/sales/raw".
    """

    kind = "databricks"

    host: str
    path: str = "/"

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", _host_name(self.host))
        object.__setattr__(self, "path", "/" + self.path.strip("/"))

    @property
    def url(self) -> str:
        """``dbfs://Volumes/...``: the form fsspec reads (see the explorer's
        ``DatabricksMapper``), and pyspark-support's ``spark_url`` turns
        into Databricks' ``dbfs:/Volumes/...``."""
        return f"dbfs://{self.path.lstrip('/')}"


def _host_name(host: str) -> str:
    """``host`` as a host name in lower case: without a scheme, port, path or
    trailing dot, e.g. "https://ADB-1.azuredatabricks.net/" gives
    "adb-1.azuredatabricks.net"."""
    host = host.strip()
    name = urlsplit(host if "//" in host else f"//{host}").hostname or ""
    return name.rstrip(".")


class DatabricksWorkspaceMapper(FileSystemMapper):
    """fsspec-databricks' ``DatabricksFileSystem``: locations with the
    workspace's host (``DatabricksLocation``), and the folders' levels of the
    explorer's ``DatabricksMapper`` (volumes, catalogs, schemas, ...).

    The host is the filesystem's Databricks SDK configuration's, which
    fsspec-databricks makes once, when the filesystem first needs it (also to
    list). A filesystem whose host cannot be read gets the explorer's own
    locations, without a host.

    Not a subclass of ``DatabricksMapper``: the explorer takes the mappers of
    fsspec's URLs (``FsspecMapper`` and its subclasses) to know nothing of
    what an instance reaches, while this one knows its workspace, so that
    two instances of one workspace are one storage.
    """

    classes = ("fsspec_databricks.spec.DatabricksFileSystem",)

    def __init__(self) -> None:
        # The explorer's own: the levels, and the locations without a host.
        self._fsspec = DatabricksMapper()

    def level(self, fs: AbstractFileSystem, path: str) -> str | None:
        return self._fsspec.level(fs, path)

    @staticmethod
    def host(fs: AbstractFileSystem) -> str:
        """The host name of ``fs``'s workspace, or "" if it cannot be read."""
        try:
            return _host_name(fs.config.host or "")
        except Exception:
            log.warning("cannot read the Databricks workspace's host", exc_info=True)
            return ""

    def to_location(self, fs: AbstractFileSystem, path: str) -> Location:
        host = self.host(fs)
        if not host:
            return self._fsspec.to_location(fs, path)
        return DatabricksLocation(host=host, path=path)

    def path_of(self, fs: AbstractFileSystem, location: Location) -> str | None:
        # Only a location of this filesystem's workspace; fsspec's URLs
        # (another kernel without this plugin) as the explorer's mapper does.
        if isinstance(location, DatabricksLocation):
            host = self.host(fs)
            return location.path if host and location.host == host else None
        return self._fsspec.path_of(fs, location)
