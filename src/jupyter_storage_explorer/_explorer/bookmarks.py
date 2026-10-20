"""StorageExplorer's bookmarks (a mixin of the class)."""

from __future__ import annotations

from typing import Any

from jupyter_storage_explorer._explorer.common import (
    error_text,
    within_top,
)
from jupyter_storage_explorer.filesystems.locations import LocalLocation


class BookmarksMixin:
    """Bookmarked folders, kept in the explorer states (states.py)."""

    def _bookmark_list(self) -> dict[str, Any]:
        """{"bookmarks": [{"filesystem", "path", "url", "local_path", "label"}]}:
        those of this explorer's storages, within their top folders, labelled
        "[storage] path" and in alphabetical order of storage, then path
        (ignoring case). "local_path" is a local folder's for "Copy path"
        (``LocalLocation.os_path``), else None."""
        bookmarks = [
            {
                "filesystem": b.filesystem,
                "path": b.path,
                "url": b.url,
                "local_path": b.location.os_path
                if isinstance(b.location, LocalLocation)
                else None,
                "label": f"[{b.filesystem}] {b.path}",
            }
            for b in self._states.bookmarks
            if b.filesystem in self._filesystems
            and within_top(b.path, self._filesystems[b.filesystem].root)
        ]
        bookmarks.sort(key=lambda b: (b["filesystem"].casefold(), b["path"].casefold()))
        return {"bookmarks": bookmarks}

    def _add_bookmark(self, path: str) -> dict[str, Any]:
        """Bookmark folder ``path`` of the storage shown; the bookmarks, or {"error"}."""
        if not within_top(path, self._root) or not self._exists_folder(path):
            return {"error": f"{path} is not a folder of this storage"}
        self._states.add_bookmark(self._filesystem, path, self._location_of(path))
        return self._bookmark_list()

    def _remove_bookmark(self, filesystem: str, path: str) -> dict[str, Any]:
        self._states.remove_bookmark(filesystem, path)
        return self._bookmark_list()

    def _open_bookmark(self, filesystem: str, path: str) -> dict[str, Any]:
        """Show bookmarked folder ``path`` of storage ``filesystem``: {} or {"error"}."""
        storage = self._filesystems.get(filesystem)
        if storage is None or not within_top(path, storage.root):
            return {"error": f"{path} is not in this explorer's storages"}
        try:
            exists = self._isdir(path, storage.fs)
        except Exception as exc:
            return {"error": error_text(exc)}
        if not exists:
            return {"error": f"{path} no longer exists"}
        if filesystem == self._filesystem:
            self._current_dir = path
        else:
            self._remembered[filesystem] = path
            self._filesystem = filesystem  # shows the folder remembered
        return {}
