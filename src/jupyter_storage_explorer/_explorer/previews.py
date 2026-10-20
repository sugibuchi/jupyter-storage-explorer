"""StorageExplorer's previews, views in tabs of their own and the right-click
menu's formats and code (a mixin of the class)."""

from __future__ import annotations

import base64
import dataclasses
from typing import TYPE_CHECKING, Any, NamedTuple

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._view_tab import ViewTab
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    DataFormat,
    MediaView,
    QueryView,
    View,
    matching_formats,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer.location import Location


class _Detected(NamedTuple):
    """An item of the storage shown with a location, and the formats it
    matches, best first (see ``PreviewsMixin._detect``)."""

    path: str
    location: Location
    is_dir: bool
    formats: list[DataFormat]


def section(view: View) -> dict[str, Any]:
    """A view other than a ``QueryView`` as JSON for the frontend (a section
    of the preview panel or a view tab); media bytes are base64-encoded."""
    data = {
        f.name: getattr(view, f.name)
        for f in dataclasses.fields(view)
        if not f.name.startswith("_")
    }
    if isinstance(view, MediaView) and view.data is not None:
        data["data"] = base64.b64encode(view.data).decode("ascii")
    return {"kind": view.kind, **jsonable(data)}


class PreviewsMixin:
    """Previews (``_preview``): the item's view in the preview panel, the data
    browser for a ``QueryView``; views in tabs of their own ("View in a new
    tab"); and the right-click menu's formats and code."""

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

    def _viewer(self, fmt: DataFormat, item: _Detected) -> Callable[[], View]:
        """Views ``item`` as ``fmt`` (by the first support installed; with
        none, what to install), each time it is called: on the storage it is
        on, also after switching storages."""
        fs, limits = self._fs, self._view_limits

        def view() -> View:
            return self._supports.view(
                fmt, item.location, fs, item.path, item.is_dir, limits=limits
            )

        return view

    def _formats_of(
        self, path: str, format: str | None
    ) -> tuple[_Detected, DataFormat]:
        """The item at ``path`` and the format to view it as: ``format`` if
        given (e.g. "text" for a JSON file), else its best. ValueError if it
        has no location or no such format."""
        item = self._detect(path)
        if item is None:
            raise ValueError(f"{path} has no URL, so it cannot be viewed")
        formats = item.formats
        if format is not None:
            formats = [f for f in formats if f.name == format]
        if not formats:
            what = f"as {format}" if format is not None else "in any format"
            raise ValueError(f"{_paths.basename(path)} cannot be viewed {what}")
        return item, formats[0]

    def _open_preview(self, path: str, format: str | None = None) -> None:
        """Preview the file or directory at ``path`` in the preview panel: the
        data browser for a ``QueryView``, else the view's section.

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
        view: View | None = None
        data: DataQuery | None = None
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
                viewer = self._viewer(fmt, item)
                view = viewer()
                if isinstance(view, QueryView):
                    data = self._new_query(view, viewer, item)
                    base["query"] = data.opening()
                else:
                    base["sections"] = [section(view)]
        except Exception as exc:
            base["error"] = error_text(exc)
            # Nothing shows them: released at once (closing is idempotent).
            if data is not None:
                data.close()
            if view is not None:
                view.close()
            view = data = None
        # The previous preview's, closed once the new one is open.
        self._release_preview()
        if data is not None:
            self._queries[path] = data
        else:
            self._preview_view = view
        self._preview = base

    def _close_preview(self) -> None:
        self._release_preview()
        self._preview = {}

    def _release_preview(self) -> None:
        """Close what the preview panel shows: the data browser's query (and
        so the view its data came from), or the view shown."""
        queries, self._queries = list(self._queries.values()), {}
        view, self._preview_view = self._preview_view, None
        for data in queries:
            data.close()
        if view is not None:
            view.close()

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

    def _new_query(
        self, view: QueryView, viewer: Callable[[], View], item: _Detected
    ) -> DataQuery:
        """The data browser's query of ``view``, the view ``viewer`` gave of
        ``item``: read again with ``viewer`` (reload).

        Settings are remembered by location, so they follow the data across
        explorers and tabs, with the mode last chosen for it. The query owns
        the view its data came from: each reload's view replaces it (closed
        once the new one is open), and closing the query closes the last.
        """
        first = [view.data]
        # The view the query's data is from, the only one open.
        current = [view]

        def source() -> Any:
            if first:  # the data just viewed, not read twice
                return first.pop()
            again = viewer()
            if not isinstance(again, QueryView):
                again.close()
                raise ValueError(f"{_paths.basename(item.path)} cannot be queried now")
            previous, current[0] = current[0], again
            previous.close()
            return again.data

        def close() -> None:
            current[0].close()

        key = item.location
        state = self._states.query(key)
        mode = state.mode if state is not None else "auto"
        limits = self._view_limits
        options = {
            "fetch": self._fetch_rows,
            "max_live_rows": limits.max_live_rows,
            "max_memory_rows": limits.max_memory_rows,
            "page_rows": limits.max_display_rows,
            "on_close": close,
        }
        try:
            return DataQuery(source, key, self._states, mode=mode, **options)
        except ValueError:
            if mode != "live":
                raise
            # "live" chosen when the format scanned lazily, and no longer does.
            first.append(view.data)
            return DataQuery(source, key, self._states, **options)

    # --- Views in tabs of their own ("View in a new tab"), which the
    # launcher's JupyterLab extension shows: a DataExplorer of the data for
    # a QueryView, else a ViewTab of the view ---

    def _view_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "view_tab": view ``path`` (as ``format``, else its best
        format) in a new widget, a ``DataExplorer`` or a ``ViewTab``, kept
        until the tab closes ("view_tab_closed"). {"model_id", "title",
        "url"} or {"error"}."""
        path = content.get("path")
        view: View | None = None
        data: DataQuery | None = None
        try:
            item, fmt = self._formats_of(path, content.get("format") or None)
            viewer = self._viewer(fmt, item)
            view = viewer()
            title = _paths.basename(path)
            if isinstance(view, QueryView):
                data = self._new_query(view, viewer, item)
                widget: DataExplorer | ViewTab = DataExplorer._of_query(
                    data,
                    self._states,
                    data.key,
                    title=title,
                    label=fmt.label,
                    height="fill",
                )
            else:
                widget = ViewTab(
                    section(view), title=title, label=fmt.label, on_close=view.close
                )
        except Exception as exc:
            if data is not None:
                data.close()
            if view is not None:
                view.close()
            return {"error": error_text(exc)}
        self._view_tabs[widget.model_id] = widget
        return {"model_id": widget.model_id, "title": title, "url": item.location.url}

    def _view_tab_closed(self, model_id: str) -> None:
        """The tab of a "view_tab" closed: its widget is no longer kept, and
        closing it closes its view."""
        widget = self._view_tabs.pop(model_id, None)
        if widget is not None:
            widget.close()

    def _query_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer the data browser's requests ("query_rows", "query_check",
        "query_save", "query_reload", "query_mode") on the data previewed."""
        data = self._queries.get(content["path"])
        if data is None:
            return {"error": "the data is no longer open; preview it again"}
        return data.handle(content) or {}

    def _menu_info(self, path: str) -> dict[str, Any]:
        """Answer "menu_info", the right-click menu's: {"formats": names of
        those matching ("Preview as"), "recipes": load code ("Python code",
        by library)}, or {"error"}."""
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
            # Recipes' packages are classes: the frontend gets their names,
            # the first the library it groups the recipes by.
            "recipes": [
                {
                    "title": r.title,
                    "packages": [p.package for p in r.requirements],
                    "code": r.code,
                }
                for r in recipes
            ],
        }
