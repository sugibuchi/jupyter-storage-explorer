"""Shared fixtures: filesystems with data in them, and targets to detect formats on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import fsspec
import polars as pl
import pytest
from explorers import Explorer, make
from fsspec.implementations.memory import MemoryFileSystem

from jupyter_storage_explorer.formats.base import Target

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def jupyter_data_dir(tmp_path_factory, monkeypatch):
    """A Jupyter data folder of each test's own: notebooks saved through
    "Open in JupyterLab" record their signatures in nbformat's notary
    database there, never in the user's."""
    folder = tmp_path_factory.mktemp("jupyter-data")
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(folder))
    return folder


@pytest.fixture
def memfs() -> MemoryFileSystem:
    """An empty in-memory filesystem (fsspec keeps one store per process, so it is cleared)."""
    fs = fsspec.filesystem("memory")
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs.clear()
    MemoryFileSystem.pseudo_dirs.append("")
    return fs


@pytest.fixture
def make_target(memfs: MemoryFileSystem) -> Callable[..., Target]:
    """Write a file (``data``) or list a directory on ``memfs`` and return its Target."""

    def make(path: str, data: bytes | None = None, url: str | None = None) -> Target:
        if data is not None:
            memfs.pipe_file(path, data)
        info: dict[str, Any] = memfs.info(path)
        children = memfs.ls(path, detail=True) if info["type"] == "directory" else None
        return Target(
            fs=memfs,
            path=path,
            url=url or f"memory://{path.lstrip('/')}",
            info=info,
            children=children,
        )

    return make


@pytest.fixture
def mem_explorer(memfs) -> Explorer:
    memfs.pipe_file("/data/a.csv", b"x,y\n1,2\n")
    memfs.pipe_file("/data/notes.md", b"# Notes\n")
    memfs.pipe_file("/data/table/_delta_log/0.json", b"{}")
    memfs.pipe_file("/other/b.txt", b"b")
    return make("/", fs=memfs)


@pytest.fixture
def local(tmp_path) -> Explorer:
    """An explorer of a local folder, as polars reads local paths."""
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(tmp_path / "data.parquet")
    (tmp_path / "notes.txt").write_bytes(b"hello\n")
    return make(str(tmp_path))
