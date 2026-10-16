"""What explorers remember: bookmarks, and the data browser's recent queries.

One ``ExplorerStates`` is shared by the explorers in the kernel unless they are
given their own (``StorageExplorer(states=...)``). With a path, it is kept in a
JSON file, so it survives restarts and is shared with other kernels using the
same file::

    {
        "bookmarks": [
            {"filesystem": "Lake", "path": "bucket/sales", "url": "s3://bucket/sales"}
        ],
        "queries": [  # the most recent first
            {"url": "s3://bucket/sales/2024.parquet", "settings": {...}, "mode": "live"}
        ]
    }

where "settings" are in the form of ``QuerySettings.to_dict()``. Other keys,
e.g. written by a later version, are kept as they are.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._query.data_query import MODES
from jupyter_storage_explorer._query.settings import (
    DEFAULT_SETTINGS,
    QuerySettings,
    QueryState,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# The keys this version reads and writes; others are kept as they are.
_KNOWN_KEYS = ("bookmarks", "queries")


@dataclass(frozen=True)
class Bookmark:
    """A folder bookmarked in an explorer.

    Attributes
    ----------
    filesystem : str
        The name of the storage in the explorer: a key of its
        ``filesystems``, or ``"default"`` for an explorer of one storage.
        Explorers show the bookmarks of the storages they have.
    path : str
        The folder, as fsspec names it on that storage.
    url : str or None
        Its location when it was bookmarked (see ``StorageExplorer._url``),
        for "Copy URL"; None if it had none.
    """

    filesystem: str
    path: str
    url: str | None = None


class ExplorerStates:
    """What explorers remember: bookmarks, and how data was last queried.

    ``StorageExplorer`` reads its bookmarks here, and the data browser
    ("Query data") restores the filters, sort order, hidden columns, widths
    and mode a dataset was last shown with. Only the ``max_queries`` datasets
    queried last are remembered.

    Parameters
    ----------
    path : str or Path, optional
        A JSON file to keep the states in, so that they survive kernel
        restarts and are shared with other kernels using it: read now,
        whenever an explorer using these states is created and before each
        change (so that changes made by other kernels are kept), and written
        at each change. Default: only in memory, while the kernel runs.
    max_queries : int, default 20
        How many datasets' queries are remembered; the least recently used
        are forgotten first.

    Raises
    ------
    ValueError
        If the file is not a JSON object.

    See Also
    --------
    QuerySettings : The data browser's settings for one dataset.

    Examples
    --------
    >>> states = ExplorerStates("~/.jupyter/storage-explorer-states.json")
    >>> states.add_bookmark("Lake", "bucket/sales", "s3://bucket/sales")
    >>> StorageExplorer(filesystems={"Lake": s3}, states=states)
    """

    def __init__(
        self, path: str | pathlib.Path | None = None, *, max_queries: int = 20
    ) -> None:
        if max_queries < 1:
            raise ValueError("max_queries must be at least 1")
        self.path = pathlib.Path(path).expanduser() if path is not None else None
        self.max_queries = max_queries
        self._bookmarks: list[Bookmark] = []
        # In the file's form: {"url", "settings": QuerySettings.to_dict(), "mode"},
        # the most recent first.
        self._queries: list[dict[str, Any]] = []
        # Keys of the file this version does not know, written back as they are.
        self._others: dict[str, Any] = {}
        self.reload()

    # --- The file ---

    def reload(self) -> None:
        """Read the file again, e.g. after another kernel changed it.

        Without a path, or if the file does not exist yet, nothing changes.
        Entries that cannot be read (e.g. edited by hand) are left out.

        Raises
        ------
        ValueError
            If the file is not a JSON object.
        """
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} must hold a JSON object")
        self._bookmarks = [
            Bookmark(b["filesystem"], b["path"], b.get("url"))
            for b in _list(data.get("bookmarks"))
            if isinstance(b, dict)
            and isinstance(b.get("filesystem"), str)
            and isinstance(b.get("path"), str)
        ]
        queries = (_read_query(q) for q in _list(data.get("queries")))
        self._queries = [q for q in queries if q is not None][: self.max_queries]
        self._others = {k: v for k, v in data.items() if k not in _KNOWN_KEYS}

    @contextlib.contextmanager
    def _changing(self) -> Iterator[None]:
        """Around a change: read the file again first, so that the change is
        made to what other kernels wrote since, then write it. A file that
        cannot be read (e.g. a typo made by hand) is not written over: the
        change is then kept in memory only."""
        try:
            self.reload()
            readable = True
        except (OSError, ValueError):
            readable = False
        yield
        if readable:
            self._write()

    def _write(self) -> None:
        """Write the file, if any: whole, through a temporary file, so that
        readers (other kernels) never see half of it."""
        if self.path is None:
            return
        data = {
            **self._others,
            "bookmarks": [
                {"filesystem": b.filesystem, "path": b.path, "url": b.url}
                for b in self._bookmarks
            ],
            "queries": self._queries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(temp)
            raise

    # --- Bookmarks ---

    @property
    def bookmarks(self) -> list[Bookmark]:
        """The bookmarks, in the order they were added.

        Returns
        -------
        list of Bookmark
            A copy of the list.
        """
        return list(self._bookmarks)

    def add_bookmark(self, filesystem: str, path: str, url: str | None = None) -> None:
        """Bookmark a folder (and write the file, if any).

        Parameters
        ----------
        filesystem : str
            The storage's name in the explorer (see ``Bookmark``).
        path : str
            The folder, as fsspec names it on that storage.
        url : str, optional
            Its location, for "Copy URL".

        Notes
        -----
        A folder already bookmarked keeps its place; its URL is updated.
        """
        bookmark = Bookmark(filesystem, path, url)
        with self._changing():
            for i, b in enumerate(self._bookmarks):
                if (b.filesystem, b.path) == (filesystem, path):
                    self._bookmarks[i] = bookmark
                    break
            else:
                self._bookmarks.append(bookmark)

    def remove_bookmark(self, filesystem: str, path: str) -> None:
        """Remove a folder's bookmark, if any (and write the file, if any).

        Parameters
        ----------
        filesystem : str
            The storage's name in the explorer.
        path : str
            The folder.
        """
        with self._changing():
            self._bookmarks = [
                b
                for b in self._bookmarks
                if (b.filesystem, b.path) != (filesystem, path)
            ]

    # --- Queries ---

    @property
    def queries(self) -> list[QueryState]:
        """The datasets' queries remembered, the most recently used first.

        Returns
        -------
        list of QueryState
        """
        return [_query_state(q) for q in self._queries]

    def query(self, url: str) -> QueryState | None:
        """How the data browser last showed a dataset.

        Parameters
        ----------
        url : str
            The dataset's location.

        Returns
        -------
        QueryState or None
            None if it is not remembered.
        """
        for q in self._queries:
            if q["url"] == url:
                return _query_state(q)
        return None

    def remember_query(
        self, url: str, settings: QuerySettings, mode: str = "auto"
    ) -> None:
        """Remember how a dataset is shown (and write the file, if any).

        It becomes the most recent; beyond ``max_queries``, the least recent
        are forgotten. Default settings in "auto" mode are forgotten rather
        than remembered: there is nothing to restore.

        Parameters
        ----------
        url : str
            The dataset's location.
        settings : QuerySettings
            Its filters, sort order, hidden columns and widths.
        mode : {"auto", "live", "memory"}, default "auto"
            Where its queries run, if the user chose.

        Raises
        ------
        ValueError
            If ``mode`` is unknown.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        entry = {"url": url, "settings": settings.to_dict(), "mode": mode}
        forget = entry["settings"] == DEFAULT_SETTINGS and mode == "auto"
        if forget and all(q["url"] != url for q in self._queries):
            return  # nothing remembered, nothing to forget (and no file to write)
        with self._changing():
            rest = [q for q in self._queries if q["url"] != url]
            self._queries = rest if forget else [entry, *rest][: self.max_queries]

    def forget_query(self, url: str) -> None:
        """Forget how a dataset was shown (and write the file, if any).

        Parameters
        ----------
        url : str
            The dataset's location.
        """
        with self._changing():
            self._queries = [q for q in self._queries if q["url"] != url]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _read_query(entry: Any) -> dict[str, Any] | None:
    """A "queries" entry of the file, checked; None if it cannot be used.

    Settings are only checked for their shape here: columns and filters are
    fitted to the data when it opens (``normalize_settings``).
    """
    if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
        return None
    settings = entry.get("settings") or {}
    try:
        settings = QuerySettings.from_dict(settings).to_dict()
    except (AttributeError, TypeError, ValueError):
        return None
    mode = entry.get("mode")
    return {
        "url": entry["url"],
        "settings": settings,
        "mode": mode if mode in MODES else "auto",
    }


def _query_state(entry: dict[str, Any]) -> QueryState:
    return QueryState(
        entry["url"],
        QuerySettings.from_dict(copy.deepcopy(entry["settings"])),
        entry["mode"],
    )


# Shared by the explorers in the kernel, unless given their own, so that their
# bookmarks are the same and data reopened in a new explorer is shown as before.
default_states = ExplorerStates()

# The states of each file given to explorers as a path (see explorer_states):
# one object per file, so explorers of the kernel see each other's changes.
_states_by_file: dict[pathlib.Path, ExplorerStates] = {}


def explorer_states(
    states: ExplorerStates | str | os.PathLike[str] | None,
) -> ExplorerStates:
    """The states an explorer uses for its ``states`` argument: the object
    given, ``default_states`` for None, or for a path, the states of that file,
    created at the first use (absolute paths, "~" resolved, identify it)."""
    if states is None:
        return default_states
    if isinstance(states, ExplorerStates):
        return states
    file = pathlib.Path(states).expanduser().resolve()
    if file not in _states_by_file:
        try:
            _states_by_file[file] = ExplorerStates(file)
        except ValueError:
            # Not a JSON object: the explorer still opens, and reports it when
            # reading the file again. Not written over until it is fixed (see
            # ExplorerStates._changing).
            unread = ExplorerStates()
            unread.path = file
            _states_by_file[file] = unread
    return _states_by_file[file]
