"""Shared fixtures: filesystems with data in them, and targets to detect formats on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import fsspec
import pytest
from fsspec.implementations.memory import MemoryFileSystem

from jupyter_storage_explorer.formats.base import Target

if TYPE_CHECKING:
    from collections.abc import Callable


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
