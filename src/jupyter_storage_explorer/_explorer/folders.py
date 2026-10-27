"""StorageExplorer's folder listing and tree (a mixin of the class)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _infos, _paths
from jupyter_storage_explorer._explorer.common import within_top
from jupyter_storage_explorer._explorer.listing import Listing
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.formats.base import detect as detect_format

if TYPE_CHECKING:
    from fsspec.spec import AbstractFileSystem

    from jupyter_storage_explorer._jobs.loader import Load
    from jupyter_storage_explorer.base import Location
    from jupyter_storage_explorer.formats import DataFormat

log = logging.getLogger(__name__)


@dataclass
class _Listed:
    """A folder as a listing's load read it (``FoldersMixin._read_folder``),
    for the main thread to show."""

    fs: AbstractFileSystem
    # The folder listed: the fallback if the one asked for is gone.
    path: str
    columns: dict[str, Any]
    # Why the folder could not be listed, or "".
    error: str
    # Folders' subfolders listed for the tree: the folder's and those of its
    # ancestors not listed before.
    tree: dict[str, list[dict[str, Any]]]
    dir_format: tuple[DataFormat, ItemContext] | None


def _ignore(_result: object) -> None:
    pass


def _entry(info: dict[str, Any]) -> dict[str, Any]:
    is_dir = info.get("type") == "directory"
    return {
        "name": _paths.basename(info["name"]),
        "path": _paths.norm(info["name"]),
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else info.get("size"),
        "mtime": _infos.mtime(info),
    }


class FoldersMixin:
    """The list of the folder shown (``_listing``) and the tree (``_tree``):
    listing folders, showing their items, following changes to them.

    Listings run as loads (see _jobs/loader.py): a slow storage leaves the
    kernel free to answer meanwhile. What a load needs of the explorer, the
    storage shown and the folders the tree lacks, is taken on the main thread
    before; its work only reads the storage, and maps and detects what it
    lists."""

    def _list(
        self, path: str, *, follow: bool = False, fallback: str | None = None
    ) -> None:
        """Show folder ``path`` in the list, once a load has listed it.

        Another folder than the one shown shows "Loading…" until then, with
        nothing selected. The folder shown, listed again, stays until its new
        listing replaces it. A later listing cancels this one.

        ``follow``: listed again while a job adds items to it, so the
        selection is kept, and an error leaves the list as it is (the job's
        end lists it again). ``fallback``: the folder shown instead if
        ``path`` is gone, e.g. a storage's remembered folder.
        """
        if self._listing_load is not None:
            self._listing_load.cancel()
        fs = self._fs
        if not follow:
            # Cleared now, not when listed: errors shown meanwhile stay, e.g.
            # the launcher's about its settings, shown once the explorer is made.
            self._error = ""
        if self._full_listing.dir != path or self._listed_fs is not fs:
            self._listed_fs = fs
            self._show_listing({**self._make_listing(path, []), "loading": True})
            self._selected = []
            self._current_dir_format = None
            self._show_current_format()
        # The tree can then be expanded down to the folder.
        unlisted = {
            folder: [a for a in self._ancestors(folder) if a not in self._tree]
            for folder in {path, fallback or path}
        }

        def work() -> _Listed:
            return self._read_folder(fs, path, fallback, unlisted)

        load = self._loader.submit(
            work, lambda listed: self._show_folder(listed, follow), _ignore
        )
        self._listing_load = None if load.ended else load

    def _read_folder(
        self,
        fs: AbstractFileSystem,
        path: str,
        fallback: str | None,
        unlisted: dict[str, list[str]],
    ) -> _Listed:
        """In a listing's load: folder ``path`` of ``fs`` listed, or
        ``fallback`` if ``path`` is no folder, with the subfolders of its
        ``unlisted`` ancestors. Logged with its count of items only: a
        folder may hold tens of thousands."""
        started = time.monotonic()
        if fallback is not None and path != fallback:
            try:
                gone = not self._isdir(path, fs)
            except Exception:
                gone = True  # cannot tell: show the fallback rather than fail
            if gone:
                path = fallback
        tree = {}
        for ancestor in unlisted[path]:
            try:
                tree[ancestor] = self._subfolders(self._ls(ancestor, fs), fs)
            except Exception:
                tree[ancestor] = []  # the folder's own error, if any, is reported
        try:
            infos = self._ls(path, fs)
        except Exception as exc:
            log.warning("Cannot list %s: %s", path, exc)
            columns = self._make_listing(path, [], fs)
            return _Listed(fs, path, columns, f"Cannot list {path}: {exc}", tree, None)
        tree[path] = self._subfolders(infos, fs)
        columns = self._make_listing(path, infos, fs)
        dir_format = self._directory_format(path, infos, fs)
        log.debug(
            "Listed %s: %d items in %.3f s%s",
            path,
            len(infos),
            time.monotonic() - started,
            f", a {dir_format[0].name} folder" if dir_format else "",
        )
        return _Listed(fs, path, columns, "", tree, dir_format)

    def _show_folder(self, listed: _Listed, follow: bool) -> None:
        """On the main thread: show the folder a listing's load read."""
        if listed.fs is not self._fs or (follow and listed.error):
            return
        with self.hold_sync():
            self._tree = {**self._tree, **listed.tree}
            self._listed_fs = listed.fs
            if listed.error:
                self._error = listed.error
            self._show_listing(listed.columns)
            if follow:
                listed_paths = {_paths.norm(p) for p in self._listed_paths()}
                kept = [p for p in self._selected if _paths.norm(p) in listed_paths]
                if kept != list(self._selected):
                    self._selected = kept
            else:
                self._selected = []
            self._current_dir_format = listed.dir_format
            self._show_current_format()
            if listed.path != self._current_dir:
                self._show_dir(listed.path)  # the folder asked for is gone

    def _show_dir(self, path: str) -> None:
        """Set ``_current_dir`` without listing it: the caller does."""
        self._dir_listed_by_caller = True
        try:
            self._current_dir = path
        finally:
            self._dir_listed_by_caller = False

    def _restore_view(self, filesystem: Any, folders: Any) -> None:
        """Show storage ``filesystem`` at its folder in ``folders`` ({storage
        name: folder}), and remember the others' for when they are shown: a
        view saved by the launcher's tab, to reopen where it was.

        Saved views may be stale or edited: storages no longer offered,
        folders outside a storage's top folder and values of the wrong type
        are ignored, and a folder that is gone gives the top folder (see
        ``_on_filesystem``).
        """
        folders = folders if isinstance(folders, dict) else {}
        wanted = {
            name: folder
            for name, folder in folders.items()
            if name in self._filesystems
            and isinstance(folder, str)
            and within_top(folder, self._filesystems[name].root)
        }
        if filesystem not in self._filesystems:
            filesystem = self._filesystem
        if filesystem != self._filesystem:
            if filesystem in wanted:
                self._remembered[filesystem] = wanted[filesystem]
            self._filesystem = filesystem  # shows its remembered folder
        elif filesystem in wanted and wanted[filesystem] != self._current_dir:
            # The folder shown stays if the saved one is gone.
            shown = self._current_dir
            self._show_dir(wanted[filesystem])
            self._list(wanted[filesystem], fallback=shown)
        # Set last: switching remembers the folder left (the top one).
        self._remembered.update(
            {name: f for name, f in wanted.items() if name != self._filesystem}
        )

    def _level_of(self, path: str, fs: AbstractFileSystem | None = None) -> str | None:
        """What the storage makes of folder ``path`` of ``fs``, by default the
        one shown (e.g. "container"), for its icon:
        ``FileSystemMapper.level``; None for a plain folder."""
        try:
            return self._mappers.level_of(fs or self._fs, path)
        except Exception:
            return None  # a mapper's error only costs an icon

    def _ancestors(self, path: str) -> list[str]:
        """Directories from the root down to (but excluding) ``path``."""
        if not path.startswith(self._root):
            return []
        out, cur = [], self._root
        for segment in filter(None, path[len(self._root) :].split("/")):
            out.append(cur)
            cur = _paths.join(cur, segment)
        return out

    def _load_children(self, path: str) -> None:
        """Show folder ``path``'s subfolders in the tree, once a load has
        listed them. A later load of the same folder cancels this one."""
        if (running := self._tree_loads.pop(path, None)) is not None:
            running.cancel()
        fs = self._fs

        def work() -> tuple[list[dict[str, Any]], str]:
            try:
                dirs = self._subfolders(self._ls(path, fs), fs)
            except Exception as exc:
                log.warning("Cannot list %s for the tree: %s", path, exc)
                return [], f"Cannot list {path}: {exc}"
            log.debug("Listed %s for the tree: %d folders", path, len(dirs))
            return dirs, ""

        def done(result: tuple[list[dict[str, Any]], str]) -> None:
            # None while submitting: without a loop, the load ends before.
            if load is not None and self._tree_loads.get(path) is load:
                del self._tree_loads[path]
            if fs is not self._fs:
                return  # another storage shown since
            dirs, error = result
            if error:
                self._error = error
            self._tree = {**self._tree, path: dirs}

        load: Load[Any] | None = None
        load = self._loader.submit(work, done, _ignore)
        if not load.ended:
            self._tree_loads[path] = load

    def _cancel_tree_loads(self) -> None:
        """Cancel the tree's loads, e.g. when the tree is listed again."""
        for load in self._tree_loads.values():
            load.cancel()
        self._tree_loads = {}

    def _subfolders(
        self, infos: list[dict[str, Any]], fs: AbstractFileSystem
    ) -> list[dict[str, Any]]:
        """The tree's entries of the folders in ``infos``, a folder's items in
        ``fs``: {"name", "path"}, with "no_url" and "level" (see ``_tree``)."""
        dirs = []
        for info in infos:
            if info.get("type") == "directory":
                child = _paths.norm(info["name"])
                dirs.append({"name": _paths.basename(child), "path": child})
                if self._mappers.location_of(fs, child) is None:
                    dirs[-1]["no_url"] = True
                if level := self._level_of(child, fs):
                    dirs[-1]["level"] = level
        dirs.sort(key=lambda d: d["name"].lower())
        return dirs

    def _make_listing(
        self,
        path: str,
        infos: list[dict[str, Any]],
        fs: AbstractFileSystem | None = None,
    ) -> dict[str, Any]:
        """The listing of directory ``path`` (its ``infos`` from ``_ls``, in
        ``fs``, by default the storage shown) for ``_listing``.

        One list per column, an item per entry: "names", "is_dir" (0 or 1),
        "sizes" (None for folders), "mtimes" and "ctimes" (modification and
        creation times, for the columns and tooltips: whole seconds, or None), and
        "format", an index into "formats", whose first name is "" (none; all
        folders), and likewise "level" into "levels" (see _level_of; "" for
        files and plain folders). Paths are not sent: an entry's is "dir" joined with its name,
        unless "paths" (otherwise None) gives them all, for a filesystem that
        names them differently. Locations are not sent either, as most are never
        used: the frontend asks for them ("locations") when copying; "no_url"
        lists the indexes of the entries without one (see _location_of).
        """
        listing: dict[str, Any] = {
            "dir": path,
            "names": [],
            "is_dir": [],
            "sizes": [],
            "mtimes": [],
            "ctimes": [],
            "formats": [""],
            "format": [],
            "levels": [""],
            "level": [],
            "paths": None,
            "no_url": [],
        }
        format_index, level_index = {"": 0}, {"": 0}
        paths = []
        # Folders can hold tens of thousands of items: their filesystem's
        # mapper is found once, and each item's location computed once. (Not
        # for no items: __init__ makes such a listing before choosing a storage.)
        if infos:
            fs = fs or self._fs
            locate = self._mappers._locator(fs)
        for i, info in enumerate(infos):
            entry = _entry(info)
            location = locate(entry["path"])
            fmt = self._file_format(info, location, fs)
            if fmt not in format_index:
                format_index[fmt] = len(listing["formats"])
                listing["formats"].append(fmt)
            listing["names"].append(entry["name"])
            listing["is_dir"].append(int(entry["type"] == "directory"))
            listing["sizes"].append(entry["size"])
            mtime = entry["mtime"]
            listing["mtimes"].append(None if mtime is None else int(mtime))
            ctime = _infos.ctime(info)
            listing["ctimes"].append(None if ctime is None else int(ctime))
            listing["format"].append(format_index[fmt])
            is_dir = entry["type"] == "directory"
            level = (self._level_of(entry["path"], fs) if is_dir else None) or ""
            if level not in level_index:
                level_index[level] = len(listing["levels"])
                listing["levels"].append(level)
            listing["level"].append(level_index[level])
            paths.append(entry["path"])
            if location is None:
                listing["no_url"].append(i)
        if any(
            p != _paths.join(path, n)
            for p, n in zip(paths, listing["names"], strict=True)
        ):
            listing["paths"] = paths
        return listing

    def _show_listing(self, columns: dict[str, Any]) -> None:
        """Keep the current directory's ``columns`` (see _make_listing) and show them."""
        self._full_listing = Listing(columns)
        self._send_listing()

    def _send_listing(self) -> None:
        """Send the current directory's listing, or for a large folder only its
        size, the frontend then asking for pages ("list")."""
        listing = self._full_listing
        self._listing_version += 1
        limit = self._max_browser_items
        if limit is not None and len(listing) > limit:
            self._listing = {
                "dir": listing.dir,
                "query": True,
                "total": len(listing),
                "version": self._listing_version,
            }
        else:
            self._listing = listing.columns

    def _list_page(self, content: dict[str, Any]) -> dict[str, Any]:
        """A page of a large folder's items: the "list" request (see Listing.query).

        {"stale": true} if the folder shown has changed since the frontend asked.
        """
        listing = self._full_listing
        if content.get("dir") != listing.dir or content.get("version") != (
            self._listing.get("version")
        ):
            return {"stale": True}
        return listing.query(
            text=content.get("text") or "",
            regex=bool(content.get("regex")),
            sort=content.get("sort", "name"),
            asc=content.get("asc", True),
            page=int(content.get("page", 0)),
            page_size=int(content.get("page_size", 100)),
            labels=self._format_labels,
        )

    def _listed_paths(self) -> list[str]:
        """Paths of the current directory's items, in listing order."""
        columns = self._full_listing.columns
        if columns["paths"] is not None:
            return columns["paths"]
        return [_paths.join(columns["dir"], name) for name in columns["names"]]

    def _refresh(self) -> None:
        """Drop cached listings and reload the current directory."""
        self._invalidate_cache()
        self._cancel_tree_loads()
        self._tree = {}
        self._list(self._current_dir)

    def _refresh_dir(self, path: str) -> None:
        """Show changes made to directory ``path`` in the list and tree."""
        self._invalidate_cache(path)
        if path == self._current_dir:
            self._list(path)
        elif path in self._tree:
            self._load_children(path)

    def _forget(self, path: str, moved_to: str | None = None) -> None:
        """Let the widget follow folder or file ``path``, moved to ``moved_to`` or deleted.

        Closes a preview of it or of something in it, drops its folders from the
        tree, and if the list shows it (or a folder in it), shows the same
        folder where it was moved to, or the deleted folder's parent.
        """
        if _paths.inside(self._preview.get("path") or "", path):
            self._close_preview()
        self._tree = {k: v for k, v in self._tree.items() if not _paths.inside(k, path)}
        if _paths.inside(self._current_dir, path):
            self._current_dir = (
                _paths.parent(path, self._fs)
                if moved_to is None
                else moved_to + _paths.norm(self._current_dir)[len(_paths.norm(path)) :]
            )

    def _update_entry(self, path: str) -> None:
        """Refresh the size and modification time shown for ``path`` in the list."""
        paths = self._listed_paths()
        if path in paths:
            entry = _entry(self._info(path))
            mtime = None if entry["mtime"] is None else int(entry["mtime"])
            self._full_listing.update(paths.index(path), entry["size"], mtime)
            self._send_listing()

    def _file_format(
        self, info: dict[str, Any], location: Location | None, fs: AbstractFileSystem
    ) -> str:
        """The format name of a listed file of ``fs`` at ``location``, e.g. "json-lines".

        Shown as the row's ``data-file-format``. Empty for folders (detecting
        them would mean listing each one), files without a URL, unrecognised
        files and files a format would confirm by their contents (reading
        each would be too slow).
        """
        if info.get("type") == "directory" or location is None:
            return ""
        path = _paths.norm(info["name"])
        ctx = ItemContext(location=location, fs=fs, path=path, info=info, children=None)
        try:
            fmt = detect_format(ctx, formats=self._formats, sniff=False)
        except Exception:
            return ""  # detection is best-effort
        return fmt.name if fmt is not None else ""

    def _show_current_format(self) -> None:
        """``_current_format``: the folder's format, if it can be viewed with
        the engine chosen (the Preview button, with nothing selected)."""
        detected = self._current_dir_format
        viewable = detected is not None and self._viewable(*detected)
        self._current_format = detected[0].name if viewable else ""

    def _directory_format(
        self, path: str, infos: list[dict[str, Any]], fs: AbstractFileSystem
    ) -> tuple[DataFormat, ItemContext] | None:
        """The format of directory ``path`` of ``fs`` given its listing, if
        any, and the directory as it was detected."""
        location = self._mappers.location_of(fs, path)
        if location is None:
            return None
        # The listing is all directory formats need, so skip fetching the
        # directory's own info.
        info = {"name": path, "type": "directory"}
        ctx = ItemContext(
            location=location, fs=fs, path=path, info=info, children=infos
        )
        try:
            fmt = detect_format(ctx, formats=self._formats)
        except Exception:
            return None  # detection is best-effort; a failure just means no preview
        return (fmt, ctx) if fmt is not None else None
