"""Files and folders as formats and supports are given them (``ItemContext``),
for their tests."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any

import fsspec

from jupyter_storage_explorer.filesystems import MapperChain, default_mappers
from jupyter_storage_explorer.formats import ItemContext

if TYPE_CHECKING:
    from jupyter_storage_explorer.location import Location


def item_of(fs: Any, path: str, location: Location | None = None) -> ItemContext:
    """The item at ``path`` of ``fs``, as explorers detect and read it; its
    location from the default mappers unless given."""
    info: dict[str, Any] = fs.info(path)
    children = fs.ls(path, detail=True) if info["type"] == "directory" else None
    if location is None:
        location = MapperChain(default_mappers()).location_of(fs, path)
    return ItemContext(
        location=location, fs=fs, path=path, info=info, children=children
    )


def local_item(path: str | pathlib.Path) -> ItemContext:
    """A local file or folder, which libraries reading by URL (polars) read."""
    return item_of(fsspec.filesystem("file"), pathlib.Path(path).as_posix())
