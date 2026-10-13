"""Helpers shared by the operations objects of this package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


def file_name(path: str) -> str:
    """The last part of ``path``, shown as the file being worked on."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def walk_files(
    source_fs: AbstractFileSystem,
    source: str,
    fs: AbstractFileSystem,
    target: str,
) -> list[tuple[str, str, int]]:
    """(file, its target, size) for each file in folder ``source``, creating
    the target folders on ``fs`` as needed (empty folders are not copied, as
    object stores have none)."""
    fs.makedirs(target, exist_ok=True)
    made = {target.rstrip("/")}
    out = []
    root = source.rstrip("/")
    for path, info in source_fs.find(source, detail=True).items():
        relative = path.rstrip("/")[len(root) :].lstrip("/")
        dest = f"{target.rstrip('/')}/{relative}"
        parent = dest.rsplit("/", 1)[0]
        if parent not in made:
            fs.makedirs(parent, exist_ok=True)
            made.add(parent)
        out.append((path, dest, info.get("size") or 0))
    return out


def remove_emptied_folder(fs: AbstractFileSystem, path: str) -> None:
    """Delete folder ``path`` once its files have been moved away (the empty
    folders left, on filesystems that have them), unless files remain, e.g.
    added meanwhile."""
    fs.invalidate_cache(path)
    if fs.exists(path) and not fs.find(path):
        fs.rm(path, recursive=True)
