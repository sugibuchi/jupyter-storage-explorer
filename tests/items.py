"""Files and folders as formats and supports are given them, for their tests."""

from __future__ import annotations

import dataclasses
import pathlib
from typing import TYPE_CHECKING, Any

import fsspec

from jupyter_storage_explorer.filesystems import MapperChain, default_mappers

if TYPE_CHECKING:
    from jupyter_storage_explorer.location import Location


@dataclasses.dataclass(frozen=True)
class Item:
    """A file or folder of a test filesystem, as explorers detect and read
    it: what ``DataFormat.matches`` gets (``match_args``) and what supports
    get (``args``: location, filesystem, path, whether a folder)."""

    location: Location
    fs: Any
    path: str
    info: dict[str, Any]
    children: list[dict[str, Any]] | None

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def match_args(self) -> tuple[Any, ...]:
        return (self.location, self.fs, self.path, self.info, self.children)

    @property
    def args(self) -> tuple[Any, ...]:
        return (self.location, self.fs, self.path, self.is_dir)


def item_of(fs: Any, path: str, location: Location | None = None) -> Item:
    """The item at ``path`` of ``fs``, its location from the default mappers
    unless given."""
    info: dict[str, Any] = fs.info(path)
    children = fs.ls(path, detail=True) if info["type"] == "directory" else None
    if location is None:
        location = MapperChain(default_mappers()).location_of(fs, path)
    return Item(location, fs, path, info, children)


def local_item(path: str | pathlib.Path) -> Item:
    """A local file or folder, which libraries reading by URL (polars) read."""
    return item_of(fsspec.filesystem("file"), pathlib.Path(path).as_posix())
