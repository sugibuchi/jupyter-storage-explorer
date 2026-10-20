"""StorageExplorer's previews, data browser and right-click menu (a mixin of the class)."""

from __future__ import annotations

import base64
import dataclasses
import functools
from typing import TYPE_CHECKING, Any, NamedTuple

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    DataFormat,
    MediaPreview,
    Preview,
    matching_formats,
)

if TYPE_CHECKING:
    from jupyter_storage_explorer.location import Location


class _Detected(NamedTuple):
    """An item of the storage shown with a location, and the formats it
    matches, best first (see ``PreviewsMixin._detect``)."""

    path: str
    location: Location
    is_dir: bool
    formats: list[DataFormat]


def _section(preview: Preview) -> dict[str, Any]:
    """A preview section as JSON for the frontend; media bytes are base64-encoded."""
    data = {f.name: getattr(preview, f.name) for f in dataclasses.fields(preview)}
    if isinstance(preview, MediaPreview) and preview.data is not None:
        data["data"] = base64.b64encode(preview.data).decode("ascii")
    return {"kind": preview.kind, **jsonable(data)}


class PreviewsMixin:
    """Previews (``_preview``), the data browser ("Query data", in the
    panel or a tab of its own) and the right-click menu's formats and code."""

    def _detect(self, path: str) -> _Detected | None:
        """The item at ``path`` of the storage shown, and the formats
        matching it. None if it has no location: it is then not treated as
        data."""
        location = self._location_of(path)
        if location is None:
            return None
        info = self._info(path)
        children = self._ls(path) if info.get("type") == "directory" else None
        formats = matching_formats(
            location, self._fs, path, info, children, formats=self._formats
        )
        return _Detected(path, location, children is not None, formats)

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
            item = self._detect(path)
            if item is None:
                raise ValueError(f"{path} has no URL, so it cannot be previewed")
            formats = item.formats
            if format is not None:
                formats = [f for f in formats if f.name == format]
                if not formats:
                    raise ValueError(f"{path} cannot be previewed as {format}")
            if formats:
                fmt = formats[0]
                base["format"] = fmt.name
                if self._supports.can_query(fmt):
                    base["query"] = self._open_query(fmt, item)
                else:
                    # By the first support installed; with none, what to
                    # install instead.
                    preview = self._supports.preview(
                        fmt,
                        item.location,
                        self._fs,
                        path,
                        item.is_dir,
                        limits=self._preview_limits,
                    )
                    base["sections"] = [_section(preview)]
        except Exception as exc:
            base["error"] = error_text(exc)
        self._preview = base

    def _close_preview(self) -> None:
        self._queries.clear()
        self._preview = {}

    # --- The query in the preview panel, for query_result() and
    # on_query_change() ---

    def _shown_query(self) -> DataQuery | None:
        """The query the preview panel shows in the data browser, or None
        (closed, loading, or showing something else)."""
        preview = self._preview
        if not preview.get("query") or preview.get("loading"):
            return None
        return self._queries.get(preview.get("path"))

    def _query_changed(self, *, reloaded: bool = False) -> None:
        """Call the ``on_query_change`` functions if ``query_result()`` has
        changed since they last were: another query shown (or none), other
        filters, sort or columns, or the data read again (``reloaded``)."""
        data = self._shown_query()
        basis = None if data is None else (data, data.result_settings())
        if basis != self._query_basis or (reloaded and data is not None):
            self._query_basis = basis
            self._query_callbacks(self)

    def _open_query(self, fmt: DataFormat, item: _Detected) -> dict[str, Any]:
        """Open ``item`` in the data browser: its columns and remembered settings.

        The frontend then asks for rows with "query_rows".
        """
        data = self._new_query(fmt, item)
        self._queries[item.path] = data
        return data.opening()

    def _new_query(self, fmt: DataFormat, item: _Detected) -> DataQuery:
        """The data browser's query of ``item`` read as ``fmt``.

        Settings are remembered by location, so they follow the data across
        explorers and tabs, with the mode last chosen for it.
        """
        # By the first support installed (can_query()); reading again
        # (reload) goes to the same storage, also after switching storages.
        source = functools.partial(
            self._supports.query, fmt, item.location, self._fs, item.path, item.is_dir
        )
        key = item.location
        state = self._states.query(key)
        mode = state.mode if state is not None else "auto"
        fetch = self._fetch_rows
        try:
            return DataQuery(source, key, self._states, mode=mode, fetch=fetch)
        except ValueError:
            if mode != "live":
                raise
            # "live" chosen when the format scanned lazily, and no longer does.
            return DataQuery(source, key, self._states, fetch=fetch)

    # --- Query data in a new tab: a DataExplorer of the same query, which the
    # launcher's JupyterLab extension shows in a tab of its own ---

    def _query_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "query_tab": open ``path`` (as ``format``, else its best
        format) in a new ``DataExplorer``, kept until the tab closes
        ("query_tab_closed"). {"model_id", "title", "url"} or {"error"}."""
        path = content.get("path")
        try:
            item = self._detect(path)
            if item is None:
                raise ValueError(f"{path} has no URL, so it cannot be queried")
            formats = item.formats
            if content.get("format"):
                formats = [f for f in formats if f.name == content["format"]]
            if not formats or not self._supports.can_query(formats[0]):
                raise ValueError(f"{_paths.basename(path)} cannot be queried")
            data = self._new_query(formats[0], item)
            explorer = DataExplorer._of_query(
                data,
                self._states,
                data.key,
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
            "url": data.key.url,
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
            item = self._detect(path)
            formats = item.formats if item is not None else []
            recipes = (
                self._supports.recipes(
                    formats[0], item.location, self._fs, path, item.is_dir
                )
                if formats
                else []
            )
        except Exception as exc:
            return {"error": error_text(exc)}
        return {
            "formats": [f.name for f in formats],
            # Requirements are classes: the frontend gets their packages.
            "recipes": [
                {"packages": [p.package for p in r.requirements], "code": r.code}
                for r in recipes
            ],
            "query": bool(formats) and self._supports.can_query(formats[0]),
        }
