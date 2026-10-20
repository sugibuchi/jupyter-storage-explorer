"""Where a file or folder is, whichever library reads it: ``Location``.

A location names a storage service's file (an Azure container's, an S3
bucket's, a file on an SFTP server or the local disk) independently of the
fsspec implementation that reaches it, so that it can travel to other
kernels, be remembered in files, and be handed to libraries that do their own
I/O (Spark, polars). Its subclasses, one per kind of storage, are in
``filesystems/locations.py``; filesystem mappers (``filesystems/mapper.py``)
turn an fsspec filesystem's paths into locations and back, and tell which
locations a filesystem reaches.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar


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
        """The URL's protocol, e.g. "abfs", "s3", "file"."""
        return self.url.partition("://")[0]

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


def trim(path: str) -> str:
    """``path`` without trailing "/", except a top folder ("/", "C:/")."""
    trimmed = path.rstrip("/")
    if trimmed.endswith(":") or (trimmed == "" and path.startswith("/")):
        return trimmed + "/"
    return trimmed
