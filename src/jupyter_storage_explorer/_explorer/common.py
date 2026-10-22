"""What the parts of StorageExplorer share: its storages, errors, and the
explorers of the kernel."""

from __future__ import annotations

import re
import weakref
from typing import TYPE_CHECKING, Any, NamedTuple

from fsspec.core import url_to_fs

from jupyter_storage_explorer import _paths

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.storage_explorer import StorageExplorer

# The explorers in this kernel, by _explorer_id: files copied in one of them
# are pasted from its own filesystem object (with its credentials), not
# found again from their URLs. Explorers in other kernels are not here.
explorers: weakref.WeakValueDictionary[str, StorageExplorer] = (
    weakref.WeakValueDictionary()
)


class Storage(NamedTuple):
    """One of an explorer's storages: its filesystem, and its top folder."""

    fs: AbstractFileSystem
    root: str


def open_storage(
    path: str | None, fs: AbstractFileSystem | None, storage_options: Mapping[str, Any]
) -> Storage:
    """A storage from a URL or path, or from an existing filesystem (and a
    path in it to start at)."""
    if fs is None:
        fs, root = url_to_fs("." if path is None else path, **storage_options)
    elif storage_options:
        raise TypeError(
            "storage options cannot be combined with an existing filesystem"
        )
    else:
        root = fs._strip_protocol(fs.root_marker if path is None else path)
    # Top-level paths strip to "" on some backends (e.g. memory), which does
    # not match the "/..." names they list.
    return Storage(fs, root or fs.root_marker)


def within_top(path: str, root: str) -> bool:
    """Whether ``path`` is in top folder ``root`` (any relative path when
    the root is "", as for DirFileSystems), without ".." parts."""
    if ".." in path.split("/"):
        return False
    return root == "" or _paths.inside(path, root)


# Py4J's errors (Spark's) start with the call that failed, e.g. "An error
# occurred while calling o57.parquet.": the Java exception is on the next line.
_PY4J_CALL = re.compile(r"An error occurred while calling [\w.$]+\.?$")

# The longest first line of an error; a longer one is cut there.
SUMMARY_CHARS = 300


def error_text(exc: Exception) -> str:
    """An error for users: the explorer's own refusals (ValueError) as they
    are, others with their type, e.g. "FileNotFoundError: ...".

    Its first line says what went wrong: the frontend shows it, and the rest
    under "Details". So a long error (e.g. Spark's, with the Java stack
    trace) starts with a line of its own: for Py4J's, the Java exception
    rather than the call; for a single line too long, its beginning."""
    text = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    summary = lines[0]
    if _PY4J_CALL.search(summary) and len(lines) > 1:
        summary = lines[1].removeprefix(":").strip()
    if len(summary) > SUMMARY_CHARS:
        summary = summary[: SUMMARY_CHARS - 1] + "…"
    return text if summary == text.splitlines()[0] else f"{summary}\n{text}"
