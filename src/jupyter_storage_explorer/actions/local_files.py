"""Local copies of remote files, for libraries that open only local files
(e.g. DuckDB and SQLite databases): ``LocalFileCache``, a cache of files
downloaded on demand, kept while views use them, and ``local_file_cache()``,
the kernel's."""

from __future__ import annotations

import atexit
import hashlib
import itertools
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

from jupyter_storage_explorer import _infos
from jupyter_storage_explorer.filesystems.locations import LocalLocation

if TYPE_CHECKING:
    from jupyter_storage_explorer.base import ItemContext, Location

# What the cache holds of an item (``LocalFileCache.status``).
CacheStatus: TypeAlias = Literal["cached", "invalid", "not_cached"]


@dataclass
class _Copy:
    """A file downloaded, and what the cache keeps of it."""

    path: Path
    # The remote file's modification time and size when it was downloaded.
    version: tuple[float | None, int | None]
    # The callers using it: get() counts one, release releases one.
    users: int = 0
    # The pending deletion, once no caller uses it.
    timer: threading.Timer | None = None


def _version(ctx: ItemContext) -> tuple[float | None, int | None]:
    """The remote file's modification time and size, as its info gives them:
    a copy is valid while they are the same."""
    return _infos.mtime(ctx.info), ctx.size


class LocalFileCache:
    """Local copies of remote files, downloaded on demand and kept while
    they are used: for libraries that open only local files, e.g. DuckDB
    and SQLite databases.

    A copy is downloaded by ``get`` and stays valid while the remote file's
    modification time is the same; one of a file changed since is invalid,
    and ``get`` downloads it again. ``get`` counts its caller as a user of
    the copy, until ``release`` releases it: a view takes the copy
    when made, and releases it in its ``on_close``, maybe with a delay, so
    that viewing the file again soon reuses the copy.

    Copies of a local file are the file itself: nothing is copied.

    The copies are in a temporary folder of the kernel's, removed when it
    exits. Use the kernel's cache, ``local_file_cache()``, so that views of
    one file share its copy.

    Parameters
    ----------
    folder : str or Path or None, default None
        Where the copies go; by default a new temporary folder, made at the
        first download and removed at the kernel's exit.

    Examples
    --------
    In a view action, asking first before a large download, or one
    of an unknown size:

    >>> cache = local_file_cache()
    >>> def open_copy():
    ...     path = cache.get(ctx)
    ...     try:
    ...         con = duckdb.connect(str(path), read_only=True)
    ...     except Exception:
    ...         cache.release(ctx.location)  # get() counted this view
    ...         raise
    ...     view = TableSetView(...)
    ...     # Closed first: a file still open cannot be deleted on Windows.
    ...     view.on_close(lambda view: con.close())
    ...     view.on_close(lambda view: cache.release(ctx.location, delay=600))
    ...     return view
    >>> large = ctx.size is None or ctx.size > limits.max_whole_file_bytes
    >>> if cache.status(ctx) != "cached" and large:
    ...     return ViewWithConfirmation(message="Download it?", factory=open_copy)
    >>> return open_copy()
    """

    def __init__(self, folder: str | Path | None = None) -> None:
        self._folder = Path(folder) if folder is not None else None
        self._own_folder = folder is None
        self._copies: dict[Location, _Copy] = {}
        # Copies replaced by a newer download while used, deleted when the
        # cache next deletes a copy (``_delete``) or at exit.
        self._stale: list[Path] = []
        # Guards the copies; downloads hold the lock of their location only.
        self._lock = threading.Lock()
        self._downloads: dict[Location, threading.Lock] = {}
        self._ids = itertools.count(1)

    def status(self, ctx: ItemContext) -> CacheStatus:
        """What the cache holds of the item: "cached", a valid copy (``get``
        reads nothing); "invalid", a copy of an older version of the file;
        "not_cached", none. For a view action to ask before downloading, e.g.
        with a ``ViewWithConfirmation``.

        Parameters
        ----------
        ctx : ItemContext
            The file, with its info as read now (e.g. when clicked).

        Returns
        -------
        {"cached", "invalid", "not_cached"}
        """
        if _is_local(ctx):
            return "cached"
        with self._lock:
            copy = self._copies.get(ctx.location)
            if copy is None or not copy.path.exists():
                return "not_cached"
            return "cached" if copy.version == _version(ctx) else "invalid"

    def get(self, ctx: ItemContext) -> Path:
        """The local path of the item's copy, downloaded first if there is
        none or it is invalid (see ``status``), and counted as used until
        ``release`` releases it: also when what follows fails, e.g. opening
        the copy. A deletion pending for the copy is cancelled.

        Downloads read the file whole, through the explorer's filesystem:
        call it in a view's work (a worker thread), not on the main thread.
        Two calls for one file at once download it once.

        Parameters
        ----------
        ctx : ItemContext
            The file, with its info as read now: its modification time tells
            whether the copy is still valid.

        Returns
        -------
        Path
            The copy's local path; for a local file, the file's own.

        Raises
        ------
        ValueError
            If the item is a folder.
        """
        if ctx.is_dir:
            raise ValueError(f"{ctx.name} is a folder: only files are copied")
        if _is_local(ctx):
            return Path(ctx.url_or_local_path)
        with self._lock:
            download = self._downloads.setdefault(ctx.location, threading.Lock())
        with download:
            with self._lock:
                copy = self._copies.get(ctx.location)
                valid = copy is not None and copy.version == _version(ctx)
                if valid and copy.path.exists():
                    return self._use(copy)
            # Downloaded outside the cache's lock: other files' calls go on.
            path = self._download(ctx)
            with self._lock:
                old = self._copies.get(ctx.location)
                users = 0
                if old is not None:
                    self._cancel(old)
                    users = old.users
                    if users:
                        self._stale.append(old.path)  # still read by its users
                    else:
                        _remove(old.path)
                copy = _Copy(path=path, version=_version(ctx), users=users)
                self._copies[ctx.location] = copy
                return self._use(copy)

    def release(self, location: Location, delay: float = 0) -> None:
        """Release one use of the file's copy (see ``get``): once no caller
        uses it, the copy is deleted after ``delay`` seconds, unless ``get``
        takes it again meanwhile. Close what reads the copy first: on
        Windows, a file still open cannot be deleted.

        Parameters
        ----------
        location : Location
            The file's location (``ctx.location``).
        delay : float, default 0
            Seconds to keep the copy unused, so that viewing the file again
            soon reuses it; 0 deletes it at once.
        """
        with self._lock:
            copy = self._copies.get(location)
            if copy is None:
                return
            copy.users = max(copy.users - 1, 0)
            if copy.users:
                return
            self._cancel(copy)
            if delay <= 0:
                self._delete(location, copy)
                return
            timer = threading.Timer(delay, self._expire, (location, copy))
            timer.daemon = True
            copy.timer = timer
            timer.start()

    def clear(self) -> None:
        """Delete every copy, used or not, and the cache's own folder: at the
        kernel's exit."""
        with self._lock:
            copies, self._copies = list(self._copies.values()), {}
            stale, self._stale = self._stale, []
        for copy in copies:
            self._cancel(copy)
            _remove(copy.path)
        for path in stale:
            _remove(path)
        if self._own_folder and self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    # --- Internals ---

    def _use(self, copy: _Copy) -> Path:
        """Count a user of ``copy``, holding the lock."""
        self._cancel(copy)
        copy.users += 1
        return copy.path

    @staticmethod
    def _cancel(copy: _Copy) -> None:
        if copy.timer is not None:
            copy.timer.cancel()
            copy.timer = None

    def _expire(self, location: Location, copy: _Copy) -> None:
        """The delay of ``release`` is over: delete the copy if still
        unused and still the file's."""
        with self._lock:
            if self._copies.get(location) is copy and not copy.users:
                self._delete(location, copy)

    def _delete(self, location: Location, copy: _Copy) -> None:
        """Delete ``copy``, holding the lock, and the stale copies that can be."""
        del self._copies[location]
        _remove(copy.path)
        self._stale = [path for path in self._stale if not _remove(path)]

    def _download(self, ctx: ItemContext) -> Path:
        """Download the item into a folder of its own, whole, then move it in
        place: a copy is never seen half written."""
        with self._lock:
            if self._folder is None:
                self._folder = Path(tempfile.mkdtemp(prefix="jse-local-files-"))
            digest = hashlib.sha256(ctx.location.url.encode()).hexdigest()[:16]
            folder = self._folder / f"{digest}-{next(self._ids)}"
        folder.mkdir(parents=True)
        # The file's name, which some libraries read (e.g. its extension).
        path = folder / ctx.name
        partial = folder / f".{ctx.name}.part"
        try:
            ctx.fs.get_file(ctx.path, str(partial))
            os.replace(partial, path)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return path


def _is_local(ctx: ItemContext) -> bool:
    """Whether the item is a local file: its own path is its copy."""
    return isinstance(ctx.location, LocalLocation)


def _remove(path: Path) -> bool:
    """Delete a copy and its folder; whether it is gone (False while a
    library still holds it open, e.g. on Windows)."""
    try:
        shutil.rmtree(path.parent)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


_CACHE = LocalFileCache()
atexit.register(_CACHE.clear)


def local_file_cache() -> LocalFileCache:
    """The kernel's cache of local copies, shared by its explorers' views,
    emptied at its exit.

    Returns
    -------
    LocalFileCache
    """
    return _CACHE
