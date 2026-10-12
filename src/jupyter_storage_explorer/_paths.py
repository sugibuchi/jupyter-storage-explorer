"""Paths as fsspec names them ("folder/file", "/" separated), and names from the browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


def norm(path: str) -> str:
    """``path`` without a trailing "/" (but "/" stays "/")."""
    return path.rstrip("/") or path


def basename(path: str) -> str:
    """The last part of ``path``, e.g. "b.csv" for "a/b.csv" (and "a/")."""
    return norm(path).rsplit("/", 1)[-1] or path


def join(parent: str, name: str) -> str:
    """``name`` in folder ``parent``; "" and "/" parents (top levels) get no extra "/"."""
    return parent + name if not parent or parent.endswith("/") else f"{parent}/{name}"


def parent(path: str, fs: AbstractFileSystem) -> str:
    """The directory containing ``path``, as the filesystem names it (e.g. "/" on memory://)."""
    path = norm(path)
    if "/" not in path:
        return ""  # a top-level item of a filesystem whose top level is "" (e.g. DirFileSystem)
    return path.rsplit("/", 1)[0] or fs.root_marker or "/"


def inside(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or something in it."""
    path, folder = norm(path), norm(folder)
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def safe_name(name: str) -> str:
    """A file name from the browser, without any directory part (so it cannot
    escape the target folder)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if name in ("", ".", ".."):
        raise ValueError(f"invalid file name: {name!r}")
    return name


def folder_name_error(name: str) -> str | None:
    """Why ``name`` cannot name a new folder, or None if it can. The same checks
    as the frontend's (see folderNameError in storage_explorer.js)."""
    if not name.strip():
        return "enter a name"
    if name != name.strip():
        return "no spaces at the start or the end"
    if name in (".", ".."):
        return f"{name!r} is not a folder name"
    if "/" in name or "\\" in name:
        return "a name, without / or \\"
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return "no control characters"
    if len(name) > 255:
        return "at most 255 characters"
    return None
