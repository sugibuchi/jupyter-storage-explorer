"""What explorers remember: bookmarks, the data browser's recent queries, the
engine chosen and the columns of the file list.

One ``ExplorerStates`` is shared by the explorers in the kernel unless they are
given their own (``StorageExplorer(states=...)``). With a path, it is kept in a
JSON file, so it survives restarts and is shared with other kernels using the
same file::

    {
        "bookmarks": [
            {"filesystem": "Lake", "path": "bucket/sales",
             "url": "s3://bucket/sales", "location": {"kind": "s3", ...}}
        ],
        "queries": [  # the most recent first
            {"url": "s3://bucket/sales/2024.parquet", "location": {...},
             "settings": {...}, "mode": "live"}
        ],
        "engine": "polars",  # the key of the engine chosen, if any
        "columns": {"standard": ["size", "mtime"]}  # the list's, by layout
    }

where "location" is ``Location.to_json()`` and "settings" are in the form of
``QuerySettings.to_dict()``. Entries written before locations have a "url"
only; a query's still matches the location of that URL. Other keys, e.g.
written by a later version, are kept as they are.
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
from jupyter_storage_explorer.base import Location
from jupyter_storage_explorer.filesystems.locations import LocalLocation

if TYPE_CHECKING:
    from collections.abc import Iterator

# The keys this version reads and writes; others are kept as they are.
_KNOWN_KEYS = ("bookmarks", "queries", "engine", "columns")


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
        Its URL: its location's, or for a bookmark made with a URL only
        (e.g. before locations), that URL.
    location : Location or None
        Its location when it was bookmarked, for "Copy URL" and "Copy path";
        None if it had none, or for a bookmark made with a URL only.
    """

    filesystem: str
    path: str
    url: str | None = None
    location: Location | None = None

    def __post_init__(self) -> None:
        if self.location is not None:
            object.__setattr__(self, "url", self.location.url)


class ExplorerStates:
    """What explorers remember: bookmarks, how data was last queried, the
    engine chosen and the file list's columns.

    ``StorageExplorer`` reads its bookmarks here, the engine its user chose
    last (``engine``) and the columns its list shows (``columns``); the data browser restores the filters, sort
    order, hidden columns, widths and mode a dataset was last shown with. Only the ``max_queries`` datasets
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
    >>> states.add_bookmark("Lake", "bucket/sales", S3Location(bucket="bucket", key="sales"))
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
        # In the file's form: {"url", "location" (if any), "settings":
        # QuerySettings.to_dict(), "mode"}, the most recent first.
        self._queries: list[dict[str, Any]] = []
        # The key of the engine chosen last, if any.
        self._engine: str | None = None
        # The file list's columns chosen, by layout ("standard", "sidebar").
        self._columns: dict[str, list[str]] = {}
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
            Bookmark(b["filesystem"], b["path"], _text(b.get("url")), _location(b))
            for b in _list(data.get("bookmarks"))
            if isinstance(b, dict)
            and isinstance(b.get("filesystem"), str)
            and isinstance(b.get("path"), str)
        ]
        queries = (_read_query(q) for q in _list(data.get("queries")))
        self._queries = [q for q in queries if q is not None][: self.max_queries]
        self._engine = _text(data.get("engine"))
        columns = data.get("columns")
        self._columns = {
            layout: [c for c in names if isinstance(c, str)]
            for layout, names in (columns.items() if isinstance(columns, dict) else ())
            if isinstance(layout, str) and isinstance(names, list)
        }
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
            "bookmarks": [_bookmark_entry(b) for b in self._bookmarks],
            "queries": self._queries,
            **({"engine": self._engine} if self._engine is not None else {}),
            **({"columns": self._columns} if self._columns else {}),
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

    def add_bookmark(
        self, filesystem: str, path: str, location: Location | str | None = None
    ) -> None:
        """Bookmark a folder (and write the file, if any).

        Parameters
        ----------
        filesystem : str
            The storage's name in the explorer (see ``Bookmark``).
        path : str
            The folder, as fsspec names it on that storage.
        location : Location or str, optional
            Its location, for "Copy URL" and "Copy path"; or its URL alone,
            for "Copy URL".

        Notes
        -----
        A folder already bookmarked keeps its place; its location is updated.
        """
        if isinstance(location, str):
            bookmark = Bookmark(filesystem, path, url=location)
        else:
            bookmark = Bookmark(filesystem, path, location=location)
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

    # --- The engine chosen ---

    @property
    def engine(self) -> str | None:
        """The key of the engine the user chose last, e.g. "polars"; None if
        none was chosen. Explorers start with it when they have it, else with
        their first engine."""
        return self._engine

    def remember_engine(self, key: str) -> None:
        """Remember the engine chosen (and write the file, if any).

        Parameters
        ----------
        key : str
            Its key, e.g. "polars".
        """
        with self._changing():
            self._engine = key

    # --- The file list's columns ---

    def columns(self, layout: str) -> list[str] | None:
        """The columns the user chose last for the file list of explorers of
        ``layout``, besides Name.

        Parameters
        ----------
        layout : str
            The explorers' layout, "standard" or "sidebar": each remembers
            its own, as the side panel has less room.

        Returns
        -------
        list of str or None
            Column keys, e.g. ``["size", "mtime"]``; None if none were chosen.
        """
        names = self._columns.get(layout)
        return None if names is None else list(names)

    def remember_columns(self, layout: str, columns: list[str]) -> None:
        """Remember the columns chosen for the file list of explorers of
        ``layout`` (and write the file, if any).

        Parameters
        ----------
        layout : str
            "standard" or "sidebar".
        columns : list of str
            Column keys, e.g. ``["size", "mtime"]``.
        """
        with self._changing():
            self._columns[layout] = list(columns)

    # --- Queries ---

    @property
    def queries(self) -> list[QueryState]:
        """The datasets' queries remembered, the most recently used first.

        Returns
        -------
        list of QueryState
        """
        return [_query_state(q) for q in self._queries]

    def query(self, key: Location | str) -> QueryState | None:
        """How the data browser last showed a dataset.

        Parameters
        ----------
        key : Location or str
            The dataset's location, or another key it is remembered by.

        Returns
        -------
        QueryState or None
            None if it is not remembered.
        """
        for q in self._queries:
            if _is_query_of(q, key):
                return _query_state(q)
        return None

    def remember_query(
        self, key: Location | str, settings: QuerySettings, mode: str = "auto"
    ) -> None:
        """Remember how a dataset is shown (and write the file, if any).

        It becomes the most recent; beyond ``max_queries``, the least recent
        are forgotten. Default settings in "auto" mode are forgotten rather
        than remembered: there is nothing to restore.

        Parameters
        ----------
        key : Location or str
            The dataset's location, or another key to remember it by.
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
        entry: dict[str, Any] = {"url": key.url if isinstance(key, Location) else key}
        if isinstance(key, Location):
            entry["location"] = key.to_json()
        entry |= {"settings": settings.to_dict(), "mode": mode}
        forget = entry["settings"] == DEFAULT_SETTINGS and mode == "auto"
        if forget and not any(_is_query_of(q, key) for q in self._queries):
            return  # nothing remembered, nothing to forget (and no file to write)
        with self._changing():
            rest = [q for q in self._queries if not _is_query_of(q, key)]
            self._queries = rest if forget else [entry, *rest][: self.max_queries]

    def forget_query(self, key: Location | str) -> None:
        """Forget how a dataset was shown (and write the file, if any).

        Parameters
        ----------
        key : Location or str
            The dataset's location, or the key it is remembered by.
        """
        with self._changing():
            self._queries = [q for q in self._queries if not _is_query_of(q, key)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _location(entry: dict[str, Any]) -> Location | None:
    """The location of a bookmark or query entry of the file; None if it has
    none (written before locations) or it cannot be read."""
    if entry.get("location") is None:
        return None
    try:
        return Location.from_json(entry["location"])
    except ValueError:
        return None


def _bookmark_entry(bookmark: Bookmark) -> dict[str, Any]:
    entry = {
        "filesystem": bookmark.filesystem,
        "path": bookmark.path,
        "url": bookmark.url,
    }
    if bookmark.location is not None:
        entry["location"] = bookmark.location.to_json()
    return entry


def _is_query_of(entry: dict[str, Any], key: Location | str) -> bool:
    """Whether a "queries" entry is the one of ``key``: of a string, an entry
    with that URL (or key); of a location, an entry of that location, or one
    with a URL only (remembered by a URL, or before locations, when a local
    file's was its plain path) if it is the location's."""
    if not isinstance(key, Location):
        return entry["url"] == key
    if "location" in entry:
        return entry["location"] == key.to_json()
    urls = {key.url, key.path} if isinstance(key, LocalLocation) else {key.url}
    return entry["url"] in urls


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
    read: dict[str, Any] = {"url": entry["url"]}
    if (location := _location(entry)) is not None:
        read["location"] = location.to_json()  # as this version writes it
    return read | {"settings": settings, "mode": mode if mode in MODES else "auto"}


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
