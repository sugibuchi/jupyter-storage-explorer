"""Where a file or folder is, whichever library reads it: ``Location``.

A location names a storage service's file (an Azure container's, an S3
bucket's, a file on an SFTP server or the local disk) independently of the
fsspec implementation that reaches it, so that it can travel to other
kernels, be remembered in files, and be handed to libraries that do their own
I/O (Spark, polars). Its subclasses, one per kind of storage, are in
``filesystems/locations.py``; filesystem mappers (``filesystems/mapper.py``)
turn an fsspec filesystem's paths into locations and back.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, ClassVar, Self

if TYPE_CHECKING:
    from collections.abc import Hashable


@dataclasses.dataclass(frozen=True, kw_only=True)
class Location:
    """Where a file or folder is, independently of fsspec's implementations.

    Locations are immutable and compare equal when they name the same item:
    their fields are normalized when they are made (e.g. hosts in lower case,
    no trailing "/"), and two locations of different kinds are never equal.
    Whether the item is a folder is not part of it.

    Subclass it for a kind of storage the predefined ones do not cover (see
    ``filesystems.locations``), with a mapper making it
    (``FileSystemMapper.to_location``). A subclass is a frozen, keyword-only
    dataclass whose fields are strings, integers or None; it names its kind
    and the field holding its path.

    Attributes
    ----------
    kind : str
        The kind's name in JSON (``to_json``), e.g. "s3". Unique.
    path_field : str
        The field holding the path within the storage, which ``join``,
        ``parent`` and ``name`` work on, e.g. "key" for S3.
    """

    kind: ClassVar[str] = ""
    path_field: ClassVar[str] = "path"

    # kind -> class, filled as subclasses are defined.
    _kinds: ClassVar[dict[str, type[Location]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "kind" in cls.__dict__:
            Location._kinds[cls.kind] = cls

    # --- What every location gives ---

    @property
    def protocol(self) -> str:
        """The URL's protocol, e.g. "abfs", "s3", "file"."""
        raise NotImplementedError

    @property
    def url(self) -> str:
        """The URL in its most common form, which the fsspec implementation
        of its protocol also reads, e.g.
        "abfs://container@account.dfs.core.windows.net/dir/a.csv"."""
        raise NotImplementedError

    @property
    def storage(self) -> Hashable:
        """The storage, without the path: equal for locations on the same
        storage (e.g. the same Azure account, S3 endpoint or SFTP server and
        user), so that one filesystem reaches them all."""
        raise NotImplementedError

    # --- Paths ---

    @property
    def name(self) -> str:
        """The last part of the path; empty at the top of the storage."""
        return self._path.rstrip("/").rpartition("/")[2]

    @property
    def parent(self) -> Self:
        """The folder holding it; at the top of the storage, itself."""
        path = self._path.rstrip("/")
        head, sep, _ = path.rpartition("/")
        if not sep:  # "a" below the top, or the top itself ("", "C:")
            head = path if path.endswith(":") else ""
        if head.endswith(":") or (head == "" and self._path.startswith("/")):
            head += "/"  # the top folder: "/", a Windows drive's "C:/"
        return self._with_path(head)

    def join(self, *parts: str) -> Self:
        """The location of ``parts`` below this one, e.g.
        ``table.join("year=2024", "a.parquet")``."""
        path = self._path
        for part in filter(None, (p.strip("/") for p in parts)):
            base = path.rstrip("/")
            path = f"{base}/{part}" if base or path.startswith("/") else part
        return self._with_path(path)

    @property
    def _path(self) -> str:
        return getattr(self, self.path_field)

    def _with_path(self, path: str) -> Self:
        return dataclasses.replace(self, **{self.path_field: path})

    # --- JSON ---

    def to_json(self) -> dict[str, Any]:
        """The location as JSON, for other kernels and files:
        ``{"kind", "protocol", "url", ...its fields}``."""
        fields = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        return {"kind": self.kind, "protocol": self.protocol, "url": self.url, **fields}

    @classmethod
    def from_json(cls, data: Any) -> Location:
        """The location ``to_json`` gave, maybe in another kernel.

        A kind this kernel does not know (e.g. another kernel's own subclass)
        gives a location of fsspec's URL (kind "fsspec"), which explorers
        only look for among their own storages.

        Raises
        ------
        ValueError
            If ``data`` is not such JSON, e.g. a field is missing.
        """
        if not isinstance(data, dict) or not isinstance(data.get("kind"), str):
            raise ValueError("not a location")
        known = Location._kinds.get(data["kind"])
        if known is None:
            known, data = (
                Location._kinds["fsspec"],
                {
                    "fsspec_protocol": data.get("protocol"),
                    "fsspec_url": data.get("url"),
                },
            )
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


def trim(path: str) -> str:
    """``path`` without trailing "/", except a top folder ("/", "C:/")."""
    trimmed = path.rstrip("/")
    if trimmed.endswith(":") or (trimmed == "" and path.startswith("/")):
        return trimmed + "/"
    return trimmed
