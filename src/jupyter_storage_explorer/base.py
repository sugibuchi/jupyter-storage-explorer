"""Where a file or folder is, whichever library reads it: ``Location``; and
the file or folder as formats and actions are given it: ``ItemContext``.

A location names a storage service's file (an Azure container's, an S3
bucket's, a file on an SFTP server or the local disk) independently of the
fsspec implementation that reaches it, so that it can travel to other
kernels, be remembered in files, and be handed to libraries that do their own
I/O (Spark, polars). Its subclasses, one per kind of storage, are in
``filesystems/locations.py``; filesystem mappers (``filesystems/mapper.py``)
turn an fsspec filesystem's paths into locations and back, and tell which
locations a filesystem reaches.

An item context is a location with the filesystem reaching it, its info and
its listing, and what formats and actions read of it (its beginning, all of
it, its children's names, its URL as libraries read it).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.util import format_size

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.views import ViewLimits


@dataclasses.dataclass(frozen=True, kw_only=True)
class Location:
    """Where a file or folder is, independently of fsspec's implementations.

    Locations are immutable and compare equal when they name the same item:
    their fields are normalized when they are made (e.g. hosts in lower case,
    no trailing "/"), and two locations of different kinds are never equal.
    Whether the item is a folder is not part of it. Which locations an fsspec
    filesystem reaches is its mapper's to tell (``FileSystemMapper.path_of``),
    as implementations see storages differently (adlfs reaches an Azure
    account's containers, Azure has a file system per container).

    Subclass it for a kind of storage the predefined ones do not cover (see
    ``filesystems.locations``), with a mapper making it
    (``FileSystemMapper.to_location``). A subclass is a frozen, keyword-only
    dataclass whose fields are strings, integers or None; it names its
    ``kind`` and gives its ``url``.

    Attributes
    ----------
    kind : str
        The kind's name in JSON (``to_json``), e.g. "s3". Unique.
    url : str
        The URL in its most common form, which the fsspec implementation of
        its protocol also reads, e.g.
        "abfs://container@account.dfs.core.windows.net/dir/a.csv". Given by
        each subclass, from its fields.
    """

    kind: ClassVar[str] = ""

    # kind -> class, filled as subclasses are defined.
    _kinds: ClassVar[dict[str, type[Location]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "kind" in cls.__dict__:
            Location._kinds[cls.kind] = cls

    @property
    def protocol(self) -> str:
        """The URL's protocol, e.g. "abfs", "s3", "file"; also of URLs with
        one "/" after it, as Databricks' ("dbfs:/Volumes/...")."""
        return self.url.partition(":")[0]

    # --- JSON ---

    def to_json(self) -> dict[str, Any]:
        """The location as JSON, for other kernels and files:
        ``{"kind", "url", ...its fields}``."""
        fields = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        return {"kind": self.kind, "url": self.url, **fields}

    @classmethod
    def from_json(cls, data: Any) -> Location:
        """The location ``to_json`` gave, maybe in another kernel.

        A kind this kernel does not know (e.g. another kernel's own subclass)
        gives a location of fsspec's URL (kind "fsspec"), which explorers
        only look for among their own storages. For the kinds it knows, the
        URL comes from the fields, never from "url".

        Raises
        ------
        ValueError
            If ``data`` is not such JSON, e.g. a field is missing.
        """
        if not isinstance(data, dict) or not isinstance(data.get("kind"), str):
            raise ValueError("not a location")
        known = Location._kinds.get(data["kind"])
        if known is None:
            known, data = Location._kinds["fsspec"], {"url": data.get("url")}
        values = {}
        for field in dataclasses.fields(known):
            if field.name in data:
                value = data[field.name]
                if value is not None and not isinstance(value, (str, int)):
                    raise ValueError(f"a location's {field.name} must be text")
                values[field.name] = value
        try:
            return known(**values)
        except (TypeError, AttributeError) as exc:  # missing, or None for text
            raise ValueError(f"not a location: {exc}") from exc


@dataclasses.dataclass(frozen=True, kw_only=True)
class ItemContext:
    """A file or folder, as formats (``DataFormat.matches``) and actions
    (functions decorated with ``view`` or ``code``) are given it, and how
    they read it.

    One object rather than parameters, so that what they are given can grow
    without changing their signatures.

    Parameters
    ----------
    location : Location
        Where it is, independently of fsspec: what formats keep what they
        find by (e.g. a Parquet dataset's layout); libraries doing their own
        I/O read ``url_or_local_path``.
    fs : AbstractFileSystem
        The explorer's filesystem it is on, with its credentials, which
        ``head``, ``head_text`` and ``read_whole`` read it through.
    path : str
        Its path in ``fs``.
    info : mapping
        fsspec's info of it (``fs.info(path)``).
    children : sequence of mapping or None
        A folder's listing (fsspec's ``ls(path, detail=True)`` entries); None
        for a file.

    Attributes
    ----------
    is_dir : bool
        Whether it is a folder (``children`` is not None).
    name : str
        The last part of its path, e.g. "a.csv".
    child_names : set of str
        The names of a folder's items; empty for a file.
    size : int or None
        A file's size in bytes, if its filesystem tells it (from ``info``).
    url_or_local_path : str
        Where most libraries read it (polars, pandas, DuckDB, ...): its
        location's URL, but a local file's plain path, which they all take
        (not all of them read ``file://`` URLs). Spark reads its own
        spelling of ``location.url`` (pyspark-support's ``spark_url``).
    url : str
        Its location's URL, ``location.url``, also of a local file
        (``file://``): what fsspec opens. Libraries reading a local file
        by its plain path take ``url_or_local_path``.
    """

    location: Location
    fs: AbstractFileSystem
    path: str
    info: Mapping[str, Any]
    children: Sequence[Mapping[str, Any]] | None
    # What ``head`` read: not a field of the item, and not copied by
    # ``dataclasses.replace``, whose context is read again.
    _heads: dict[str, Any] = dataclasses.field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def name(self) -> str:
        return _paths.basename(self.path)

    @property
    def child_names(self) -> set[str]:
        return {_paths.basename(c["name"]) for c in self.children or ()}

    @property
    def size(self) -> int | None:
        return self.info.get("size")

    @property
    def url_or_local_path(self) -> str:
        # Here, as the predefined locations import this module.
        from jupyter_storage_explorer.filesystems.locations import (  # noqa: PLC0415
            LocalLocation,
        )

        location = self.location
        return location.path if isinstance(location, LocalLocation) else location.url

    @property
    def url(self) -> str:
        return self.location.url

    def head(self, size: int) -> bytes:
        """The first ``size`` bytes of the file, without reading the rest.

        Read once for each context: detection and the actions often ask for
        the same beginning (a signature, a CSV file's separator in each
        engine's code), and on cloud storages each read is a round trip."""
        read = self._heads.get("bytes")
        if read is not None and (len(read) >= size or self._heads["whole"]):
            return read[:size]
        with self.fs.open(self.path, "rb") as f:
            data = f.read(size)
        self._heads.update(bytes=data, whole=len(data) < size)
        return data

    def head_text(self, size: int) -> tuple[str, bool]:
        """The first ``size`` bytes decoded as UTF-8, and whether the file is
        longer.

        When the file is longer, the text is cut after its last complete line.
        """
        data = self.head(size + 1)
        truncated = len(data) > size
        if truncated:
            data = data[:size]
            if (end := data.rfind(b"\n")) >= 0:
                data = data[: end + 1]
        return data.decode("utf-8-sig", errors="replace"), truncated

    def read_whole(self, limits: ViewLimits) -> bytes:
        """The whole file, for formats that cannot be read in part.
        ValueError if it is larger than ``limits.max_whole_file_bytes``."""
        if self.size is not None and self.size > limits.max_whole_file_bytes:
            limit = format_size(limits.max_whole_file_bytes)
            raise ValueError(f"too large to view (over {limit})")
        return self.fs.cat_file(self.path)
