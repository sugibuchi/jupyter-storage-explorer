"""Properties, "Properties" in the right-click menu: a file's fsspec info, or
the totals of the files and folders in a selection.

Totals come from the operations' ``measure`` (see filesystems/operation.py), given a
``Progress``: large trees take long, so the explorer runs ``scan`` as a job
(see runner.py), which shows the files found so far and can be cancelled.
Nothing here touches the widget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _infos, _paths
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer.filesystems.operation import (
    Measurement,
    OperationCancelled,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer._jobs.operation_chain import OperationChain
    from jupyter_storage_explorer.filesystems.operation import Progress


def file_properties(info: dict[str, Any], url: str | None) -> dict[str, Any]:
    """A file's properties for the frontend: the ones every filesystem has
    (name, path, URL, size, modification time, whichever key gives it), and
    "info", everything its filesystem's ``info()`` returned, as JSON values."""
    return {
        "name": _paths.basename(info["name"]),
        "path": _paths.norm(info["name"]),
        "url": url,
        "type": info.get("type"),
        "size": info.get("size"),
        "mtime": _infos.mtime(info),
        "info": jsonable(info),
    }


def scan(
    ops: OperationChain,
    fs: AbstractFileSystem,
    paths: Sequence[str],
    progress: Progress,
) -> dict[str, Any]:
    """Count the files and folders of ``paths`` on ``fs`` with ``ops.measure``:
    for a single path, what it holds; otherwise the items themselves (a
    folder selected counts as one) and what their folders hold.

    Returns {"files", "folders", "bytes", "oldest", "newest", "errors"}, the
    oldest and newest files as {"mtime", "path"} (None when no file has a
    modification time); with "cancelled": True and the counts so far if the
    user cancelled. Items and folders that cannot be read are left out, with
    an error each.
    """
    total = Measurement()
    try:
        for path in paths:
            progress.check()
            try:
                measurement = ops.measure(fs, path, progress)
                if len(paths) > 1 and fs.isdir(path):
                    measurement.folders += 1
            except OSError as exc:
                total.errors.append(f"{path}: {exc}")
                continue
            total.merge(measurement)
            if not measurement.complete:
                break
    except OperationCancelled:
        total.complete = False
    return _result(total)


def _result(measurement: Measurement) -> dict[str, Any]:
    """A measurement as the job's result, for the frontend."""

    def stamp(found: tuple[float, str] | None) -> dict[str, Any] | None:
        return None if found is None else {"mtime": found[0], "path": found[1]}

    result = {
        "files": measurement.files,
        "folders": measurement.folders,
        "bytes": measurement.bytes,
        "oldest": stamp(measurement.oldest),
        "newest": stamp(measurement.newest),
        "errors": measurement.errors,
    }
    return result if measurement.complete else {**result, "cancelled": True}
