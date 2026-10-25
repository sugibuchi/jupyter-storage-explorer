"""Helpers for testing plugins' components without a browser: items as the
explorer gives them to formats and actions (``ItemContext``), on fsspec's
memory filesystem or local files.

Needs pytest (for the fixtures). In a plugin's ``tests/conftest.py``::

    from jupyter_storage_explorer.testing import make_item, memfs  # noqa: F401

then, in its tests::

    def test_view(make_item):
        item = make_item("/a.csv", b"x,y\\n1,2\\n")
        view = csv_view(Csv(), item, CsvByDuckDBOptions(), ViewLimits())
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any

import fsspec
import pytest
from fsspec.implementations.memory import MemoryFileSystem

from jupyter_storage_explorer.filesystems import MapperChain, default_mappers
from jupyter_storage_explorer.formats import ItemContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer.location import Location

__all__ = ["item_of", "local_item", "make_item", "memfs"]


def item_of(fs: Any, path: str, location: Location | None = None) -> ItemContext:
    """The item at ``path`` of ``fs``, as explorers detect and read it.

    Parameters
    ----------
    fs : fsspec.AbstractFileSystem
        The filesystem the item is on.
    path : str
        Its path there.
    location : Location, optional
        Where it is; by default from the default mappers (e.g. an
        ``S3Location`` to test code reading from S3).

    Returns
    -------
    ItemContext
        With its fsspec info, and its listing for a folder.
    """
    info: dict[str, Any] = fs.info(path)
    children = fs.ls(path, detail=True) if info["type"] == "directory" else None
    if location is None:
        location = MapperChain(default_mappers()).location_of(fs, path)
    return ItemContext(
        location=location, fs=fs, path=path, info=info, children=children
    )


def local_item(path: str | pathlib.Path) -> ItemContext:
    """A local file or folder, for libraries reading by URL (e.g. polars,
    which cannot read fsspec's memory filesystem).

    Parameters
    ----------
    path : str or pathlib.Path
        The local path, e.g. in pytest's ``tmp_path``.

    Returns
    -------
    ItemContext
    """
    return item_of(fsspec.filesystem("file"), pathlib.Path(path).as_posix())


@pytest.fixture
def memfs() -> MemoryFileSystem:
    """An empty in-memory filesystem: fsspec keeps one store per process, so
    it is cleared."""
    fs = fsspec.filesystem("memory")
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs.clear()
    MemoryFileSystem.pseudo_dirs.append("")
    return fs


@pytest.fixture
def make_item(memfs: MemoryFileSystem) -> Callable[..., ItemContext]:
    """A function writing a file (``data``) or listing a folder on ``memfs``
    and returning it as an ``ItemContext``: ``make_item(path, data=None,
    location=None)``, ``location`` instead of its own, e.g. an S3 one."""

    def make(
        path: str, data: bytes | None = None, location: Location | None = None
    ) -> ItemContext:
        if data is not None:
            memfs.pipe_file(path, data)
        return item_of(memfs, path, location)

    return make
