"""StorageExplorer's folder listing and tree (a mixin of the class)."""

from __future__ import annotations

from typing import Any

from jupyter_storage_explorer import _infos, _paths
from jupyter_storage_explorer._explorer.listing import Listing
from jupyter_storage_explorer.formats import DataFormat, ItemContext
from jupyter_storage_explorer.formats.base import detect as detect_format


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
    listing folders, showing their items, following changes to them."""

    def _list(self, path: str) -> None:
        # Make sure the tree can be expanded down to the current directory.
        for ancestor in self._ancestors(path):
            if ancestor not in self._tree:
                self._load_children(ancestor)
        try:
            infos = self._ls(path)
        except Exception as exc:
            self._error = f"Cannot list {path}: {exc}"
            self._show_listing(self._make_listing(path, []))
            self._selected = []
            self._current_dir_format = None
            self._show_current_format()
            return
        self._error = ""
        self._set_children(path, infos)
        self._show_listing(self._make_listing(path, infos))
        self._selected = []
        self._current_dir_format = self._directory_format(path, infos)
        self._show_current_format()

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
        try:
            infos = self._ls(path)
        except Exception as exc:
            self._error = f"Cannot list {path}: {exc}"
            infos = []
        self._set_children(path, infos)

    def _set_children(self, path: str, infos: list[dict[str, Any]]) -> None:
        dirs = []
        for info in infos:
            if info.get("type") == "directory":
                child = _paths.norm(info["name"])
                dirs.append({"name": _paths.basename(child), "path": child})
                if self._location_of(child) is None:
                    dirs[-1]["no_url"] = True
        dirs.sort(key=lambda d: d["name"].lower())
        self._tree = {**self._tree, path: dirs}

    def _make_listing(self, path: str, infos: list[dict[str, Any]]) -> dict[str, Any]:
        """The listing of directory ``path`` (its ``infos`` from ``_ls``) for ``_listing``.

        One list per column, an item per entry: "names", "is_dir" (0 or 1),
        "sizes" (None for folders), "mtimes" and "ctimes" (modification and
        creation times, for the columns and tooltips: whole seconds, or None), and
        "format", an index into "formats", whose first name is "" (none; all
        folders). Paths are not sent: an entry's is "dir" joined with its name,
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
            "paths": None,
            "no_url": [],
        }
        format_index = {"": 0}
        paths = []
        for i, info in enumerate(infos):
            entry = _entry(info)
            fmt = self._file_format(info)
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
            paths.append(entry["path"])
            if self._location_of(entry["path"]) is None:
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

    def _file_format(self, info: dict[str, Any]) -> str:
        """The format name of a listed file, e.g. "json-lines".

        Shown as the row's ``data-file-format``. Empty for folders (detecting
        them would mean listing each one), files without a URL and
        unrecognised files.
        """
        path = _paths.norm(info["name"])
        location = self._location_of(path)
        if info.get("type") == "directory" or location is None:
            return ""
        ctx = ItemContext(
            location=location, fs=self._fs, path=path, info=info, children=None
        )
        try:
            fmt = detect_format(ctx, formats=self._formats)
        except Exception:
            return ""  # detection is best-effort
        return fmt.name if fmt is not None else ""

    def _show_current_format(self) -> None:
        """``_current_format``: the folder's format, if it can be viewed with
        the engine chosen (the Preview button, with nothing selected)."""
        fmt = self._current_dir_format
        self._current_format = fmt.name if fmt and self._viewable(fmt) else ""

    def _directory_format(
        self, path: str, infos: list[dict[str, Any]]
    ) -> DataFormat | None:
        """The format of directory ``path`` given its listing, if any."""
        location = self._location_of(path)
        if location is None:
            return None
        # The listing is all directory formats need, so skip fetching the
        # directory's own info.
        info = {"name": path, "type": "directory"}
        ctx = ItemContext(
            location=location, fs=self._fs, path=path, info=info, children=infos
        )
        try:
            return detect_format(ctx, formats=self._formats)
        except Exception:
            return None  # detection is best-effort; a failure just means no preview
