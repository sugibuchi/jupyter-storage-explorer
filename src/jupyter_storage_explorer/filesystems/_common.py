"""Helpers shared by the operations objects of this package."""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.operations import Measurement, OperationCancelled

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.operations import Progress


def file_name(path: str) -> str:
    """The last part of ``path``, shown as the file being worked on."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def measure_found(path: str, found: dict[str, dict[str, Any]]) -> Measurement:
    """A folder's measurement from one recursive listing of it: ``found``,
    from ``find(path, withdirs=True, detail=True)``, which may include the
    folder itself."""
    top = path.rstrip("/")
    measurement = Measurement()
    infos = [i for name, i in found.items() if name.rstrip("/") != top]
    measurement.folders = sum(i.get("type") == "directory" for i in infos)
    measurement.add_files([i for i in infos if i.get("type") != "directory"])
    return measurement


def measure_by_folder(
    path: str,
    list_folders: Callable[[Sequence[str]], Sequence[list[dict[str, Any]] | Exception]],
    progress: Progress,
    batch: int = 1,
) -> Measurement:
    """A folder's measurement listed folder by folder, for ``measure`` with
    a progress: ``list_folders(paths)`` lists up to ``batch`` folders, each
    giving its ``ls(detail=True)`` entries or the exception it raised.

    Reports each folder's files to ``progress`` and checks for a cancel
    between listings, which stops it with what was found so far (``complete``
    False). Folders that cannot be listed (``OSError``) are left out, with an
    error each; other exceptions are raised.
    """
    measurement = Measurement()
    pending = collections.deque([path.rstrip("/")])
    try:
        while pending:
            progress.check()
            folders = [pending.popleft() for _ in range(min(batch, len(pending)))]
            progress.working_on(file_name(folders[0]) or folders[0])
            for folder, listing in zip(folders, list_folders(folders), strict=True):
                if isinstance(listing, OSError):
                    measurement.errors.append(f"{folder}: {listing}")
                    continue
                if isinstance(listing, Exception):
                    raise listing
                files = []
                for info in listing:
                    name = info["name"].rstrip("/")
                    if name == folder:
                        continue  # some filesystems list a folder in itself
                    if info.get("type") == "directory":
                        measurement.folders += 1
                        pending.append(name)
                    else:
                        files.append(info)
                measurement.add_files(files)
                progress.advance(
                    files=len(files), bytes=sum(i.get("size") or 0 for i in files)
                )
    except OperationCancelled:
        measurement.complete = False
    return measurement


def measure_file(info: dict[str, Any], progress: Progress | None) -> Measurement:
    """A file's measurement, from its info dict."""
    measurement = Measurement()
    measurement.add_files([info])
    if progress is not None:
        progress.advance(files=1, bytes=measurement.bytes)
    return measurement


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
