"""StorageExplorer's previews, data browser and right-click menu (a mixin of the class)."""

from __future__ import annotations

import base64
import dataclasses
import functools
from typing import Any

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    DataFormat,
    MediaPreview,
    Preview,
    Target,
    matching_formats,
)
from jupyter_storage_explorer.query import DataQuery


def _section(preview: Preview) -> dict[str, Any]:
    """A preview section as JSON for the frontend; media bytes are base64-encoded."""
    data = {f.name: getattr(preview, f.name) for f in dataclasses.fields(preview)}
    if isinstance(preview, MediaPreview) and preview.data is not None:
        data["data"] = base64.b64encode(preview.data).decode("ascii")
    return {"kind": preview.kind, **jsonable(data)}


class PreviewsMixin:
    """Previews (``_preview``), the data browser ("Query data", in the
    panel or a tab of its own) and the right-click menu's formats and code."""

    def _detect(self, path: str) -> tuple[Target | None, list[DataFormat]]:
        """The target at ``path`` and the formats matching it, best first.

        (None, []) if ``path`` has no URL: it is then not treated as data.
        """
        url = self._url(path)
        if url is None:
            return None, []
        info = self._info(path)
        children = self._ls(path) if info.get("type") == "directory" else None
        target = Target(fs=self._fs, path=path, url=url, info=info, children=children)
        return target, matching_formats(target, self._formats)

    def _open_preview(self, path: str, format: str | None = None) -> None:
        """Preview the file or directory at ``path`` in the preview panel.

        ``format`` names one of the formats matching it (e.g. "text" for a JSON
        file); by default the best match is used.
        """
        base = {
            "path": path,
            "name": _paths.basename(path),
            "format": None,
            "sections": [],
            "error": "",
        }
        # Shown while the (possibly remote) reads below run.
        self._preview = {**base, "loading": True}
        try:
            target, formats = self._detect(path)
            if target is None:
                raise ValueError(f"{path} has no URL, so it cannot be previewed")
            if format is not None:
                formats = [f for f in formats if f.name == format]
                if not formats:
                    raise ValueError(f"{path} cannot be previewed as {format}")
            if formats:
                fmt = formats[0]
                base["format"] = fmt.name
                if fmt.can_query():
                    base["query"] = self._open_query(path, fmt, target)
                else:
                    base["sections"] = [
                        _section(s) for s in fmt.preview(target, self._preview_limits)
                    ]
        except Exception as exc:
            base["error"] = error_text(exc)
        self._preview = base

    def _close_preview(self) -> None:
        self._queries.clear()
        self._preview = {}

    def _open_query(self, path: str, fmt: DataFormat, target: Target) -> dict[str, Any]:
        """Open ``path`` in the data browser: its columns and remembered settings.

        The frontend then asks for rows with "query_rows".
        """
        data = self._new_query(fmt, target)
        self._queries[path] = data
        return data.opening()

    def _new_query(self, fmt: DataFormat, target: Target) -> DataQuery:
        """The data browser's query of ``target`` read as ``fmt``.

        Settings are remembered by URL, so they follow the data across
        explorers and tabs, with the mode last chosen for it.
        """
        scan = functools.partial(fmt.scan, target.url, target.is_dir)
        state = self._states.query(target.url)
        mode = state.mode if state is not None else "auto"
        fetch = self._fetch_rows
        try:
            return DataQuery(scan, target.url, self._states, mode=mode, fetch=fetch)
        except ValueError:
            if mode != "live":
                raise
            # "live" chosen when the format scanned lazily, and no longer does.
            return DataQuery(scan, target.url, self._states, fetch=fetch)

    # --- Query data in a new tab: a DataExplorer of the same query, which the
    # launcher's JupyterLab extension shows in a tab of its own ---

    def _query_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "query_tab": open ``path`` (as ``format``, else its best
        format) in a new ``DataExplorer``, kept until the tab closes
        ("query_tab_closed"). {"model_id", "title", "url"} or {"error"}."""
        path = content.get("path")
        try:
            target, formats = self._detect(path)
            if target is None:
                raise ValueError(f"{path} has no URL, so it cannot be queried")
            if content.get("format"):
                formats = [f for f in formats if f.name == content["format"]]
            if not formats or not formats[0].can_query():
                raise ValueError(f"{_paths.basename(path)} cannot be queried")
            explorer = DataExplorer._of_query(
                self._new_query(formats[0], target),
                self._states,
                target.url,
                title=_paths.basename(path),
                label=formats[0].label,
                height="fill",
            )
        except Exception as exc:
            return {"error": error_text(exc)}
        self._query_tabs[explorer.model_id] = explorer
        return {
            "model_id": explorer.model_id,
            "title": _paths.basename(path),
            "url": target.url,
        }

    def _query_tab_closed(self, model_id: str) -> None:
        """The tab of a "query_tab" closed: its DataExplorer is no longer kept."""
        explorer = self._query_tabs.pop(model_id, None)
        if explorer is not None:
            explorer.close()

    def _query_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer the data browser's requests ("query_rows", "query_check",
        "query_save", "query_reload", "query_mode") on the data previewed."""
        data = self._queries.get(content["path"])
        if data is None:
            return {"error": "the data is no longer open; preview it again"}
        return data.handle(content) or {}

    def _menu_info(self, path: str) -> dict[str, Any]:
        """Answer "menu_info", the right-click menu's: {"formats": names of
        those matching ("Preview as"), "recipes": load code ("Python code"),
        "query": whether it opens in the data browser}, or {"error"}."""
        try:
            target, formats = self._detect(path)
            recipes = formats[0].recipes(target) if formats else []
        except Exception as exc:
            return {"error": error_text(exc)}
        return {
            "formats": [f.name for f in formats],
            "recipes": [dataclasses.asdict(r) for r in recipes],
            "query": bool(formats) and formats[0].can_query(),
        }
