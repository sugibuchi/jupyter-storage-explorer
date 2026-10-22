"""StorageExplorer's previews, views in tabs of their own and the right-click
menu's formats and code (a mixin of the class)."""

from __future__ import annotations

import atexit
import base64
import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Any, NamedTuple

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text, explorers
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.table_set import SEPARATOR, TableSet
from jupyter_storage_explorer._table_set_tab import TableSetTab
from jupyter_storage_explorer._view_tab import ViewTab
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    DataFormat,
    ItemContext,
    MediaView,
    QueryView,
    TableSetView,
    TableView,
    View,
)
from jupyter_storage_explorer.formats.base import matching_formats

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import EllipsisType

log = logging.getLogger(__name__)


# How long a click's detection is reused: long enough for its menu or preview,
# short enough that files changed elsewhere show on the next click.
_DETECTED_SECONDS = 5.0


class _Detected(NamedTuple):
    """An item of the storage shown with a location, as formats and supports
    are given it, and the formats it matches, best first (see
    ``PreviewsMixin._detect``)."""

    ctx: ItemContext
    formats: list[DataFormat]


def _close_views_at_exit() -> None:
    """Close the views of the kernel's explorers as it exits (shut down or
    restarted), so that what they hold is released: e.g. temporary copies of
    files, connections. Each explorer's, even if another's fails. A kernel
    killed outright runs no exit function."""
    for explorer in list(explorers.values()):
        try:
            explorer._release_views()
        except Exception:
            log.exception("Closing the views of an explorer failed")


atexit.register(_close_views_at_exit)


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
    if isinstance(view, TableView):
        data["note"] = "; ".join(filter(None, [_rows_note(view), view.note]))
    return {"kind": view.kind, **jsonable(data)}


def _rows_note(table: TableView) -> str:
    """How many rows a table view shows, e.g. "First 100 of 1,234 rows"."""
    count, unit = len(table.rows), table.unit
    if not table.more:
        return f"{count:,} {unit}"
    if table.total is not None:
        return f"First {count:,} of {table.total:,} {unit}"
    return f"First {count:,} {unit}"


class PreviewsMixin:
    """Previews (``_preview``): the item's view in the preview panel, the data
    browser for a ``QueryView``; views in tabs of their own ("View in a new
    tab"); and the right-click menu's formats and code."""

    def _detect(self, path: str) -> _Detected | None:
        """The item at ``path`` of the storage shown, and the formats
        matching it. None if it has no location: it is then not treated as
        data.

        A click asks for the same item several times: its selection, then
        its menu or preview. On cloud storages each detection costs round
        trips (its info, a folder's listings, a file's first bytes). So the
        last item detected is kept for ``_DETECTED_SECONDS``, for the storage
        shown. Refreshing, or a job's changes, forget it
        (``_invalidate_cache``)."""
        key = (id(self._fs), path)
        now = time.monotonic()
        if self._detected is not None:
            detected_key, when, item = self._detected
            if detected_key == key and now - when < _DETECTED_SECONDS:
                return item
        item = self._detect_now(path)
        self._detected = (key, now, item)
        return item

    def _detect_now(self, path: str) -> _Detected | None:
        location = self._location_of(path)
        if location is None:
            return None
        info = self._info(path)
        children = self._ls(path) if info.get("type") == "directory" else None
        ctx = ItemContext(
            location=location, fs=self._fs, path=path, info=info, children=children
        )
        return _Detected(ctx, matching_formats(ctx, formats=self._formats))

    def _engine_label(self, key: str | None) -> str:
        """The label of the engine of ``key``, e.g. "Polars"; "" for the
        built-in views (None)."""
        if key is None:
            return ""
        engine = next((e for e in self._supports.engines if e.key == key), None)
        return engine.label if engine is not None else key

    def _view_engine(
        self, fmt: DataFormat, name: str, engine: str | EllipsisType | None = ...
    ) -> str | None:
        """The engine viewing an item named ``name`` as ``fmt``: ``engine``
        (a key; None for the built-in views) if given, "Preview as"; by
        default (...), the one chosen (``_engine``), or the built-in views
        for formats it does not handle. ValueError if that cannot view it."""
        if engine is not ...:
            if engine not in self._supports.viewers(fmt):
                with_ = self._engine_label(engine) or "the built-in views"
                raise ValueError(f"{name} cannot be viewed as {fmt.label} with {with_}")
            return engine
        try:
            return self._supports.engine_for(fmt, self._engine or None)
        except LookupError:
            if not self._supports.viewers(fmt):
                # Nothing installed views it: the engines come with plugins.
                raise ValueError(
                    f"{name} cannot be viewed as {fmt.label}: no library viewing "
                    f"it is installed, e.g. pip install "
                    f'"jupyter-storage-explorer[polars]"'
                ) from None
            raise ValueError(
                f"{name} cannot be viewed as {fmt.label} with "
                f"{self._engine_label(self._engine)}: choose another engine in "
                f'"Preview as"'
            ) from None

    def _viewable(self, fmt: DataFormat) -> bool:
        """Whether ``fmt`` can be viewed with the engine chosen (or the
        built-in views): the Preview button's, and the menu's."""
        try:
            self._supports.engine_for(fmt, self._engine or None)
        except LookupError:
            return False
        return True

    def _viewer(
        self, fmt: DataFormat, item: _Detected, engine: str | None
    ) -> Callable[[], View]:
        """Views ``item`` as ``fmt`` with ``engine`` (a key; None for the
        built-in views; see ``_view_engine``), each time it is called: on
        the storage it is on (its context's), also after switching storages.
        The first time with the context ``item`` was detected with; later (the
        data browser's reload) with one read again (``_refreshed``), so the
        view is of the item as it is now."""
        limits = self._view_limits
        viewed = [False]

        def view() -> View:
            ctx = self._refreshed(fmt, item.ctx) if viewed[0] else item.ctx
            viewed[0] = True
            return self._supports.view(fmt, ctx, limits, engine)

        return view

    def _refreshed(self, fmt: DataFormat, ctx: ItemContext) -> ItemContext:
        """``ctx`` with the item's info and listing read again, on its own
        filesystem, without fsspec's cached listings: what a reload views. Its
        format is checked again (which refreshes what ``fmt`` keeps of it, e.g.
        a Parquet dataset's layout); ValueError if it no longer matches, or
        the item is gone."""
        self._invalidate_cache(ctx.path, ctx.fs)
        try:
            info = self._info(ctx.path, ctx.fs)
        except FileNotFoundError:
            raise ValueError(f"{ctx.name} is gone") from None
        children = (
            self._ls(ctx.path, ctx.fs) if info.get("type") == "directory" else None
        )
        fresh = dataclasses.replace(ctx, info=info, children=children)
        if not fmt.matches(fresh):
            raise ValueError(f"{ctx.name} no longer matches {fmt.label}")
        return fresh

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

    def _open_preview(
        self,
        path: str,
        format: str | None = None,
        engine: str | EllipsisType | None = ...,
    ) -> None:
        """Preview the file or directory at ``path`` in the preview panel: the
        data browser for a ``QueryView``, a ``TableSetView``'s tables, else
        the view's section (see ``_show``).

        ``format`` names one of the formats matching it (e.g. "text" for a JSON
        file); by default the best match is used. ``engine`` (a key; None for
        the built-in views) views it instead of the one chosen (see
        ``_view_engine``).
        """
        base = {
            "path": path,
            "name": _paths.basename(path),
            "format": None,
            "engine": None,
            "engine_label": "",
            "sections": [],
            "error": "",
        }
        # Shown while the (possibly remote) reads below run.
        self._preview = {**base, "loading": True}
        # What shows it: the view, else its query or tables, which own it.
        shown: View | DataQuery | TableSet | None = None
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
                key = self._view_engine(fmt, item.ctx.name, engine)
                base["engine"], base["engine_label"] = key, self._engine_label(key)
                viewer = self._viewer(fmt, item, key)
                shown = viewer()
                shown = self._show(shown, viewer, item, base)
        except Exception as exc:
            base["error"] = error_text(exc)
            # Nothing shows it: released at once.
            if shown is not None:
                shown.close()
            shown = None
        # The previous preview's, closed once the new one is open.
        self._release_preview()
        if isinstance(shown, DataQuery):
            self._queries[path] = shown
        elif isinstance(shown, TableSet):
            self._table_sets[path] = shown
        else:
            self._preview_view = shown
        self._preview = base

    def _show(
        self,
        view: View,
        viewer: Callable[[], View],
        item: _Detected,
        preview: dict[str, Any],
    ) -> View | DataQuery | TableSet:
        """Set what ``preview`` shows of ``view``, which ``viewer`` gave of
        ``item``: "query" (the data browser's) for a ``QueryView``,
        "table_set" for a ``TableSetView``, else "sections". Returns what
        then owns the view: its query, its tables, or the view. The view is
        closed if they cannot be made."""
        try:
            if isinstance(view, QueryView):
                data = self._new_query(view, viewer, item)
                preview["query"] = data.opening()
                return data
            if isinstance(view, TableSetView):
                tables = self._table_set(view, viewer, item)
                preview["table_set"] = tables.opening()
                return tables
        except Exception:
            view.close()
            raise
        preview["sections"] = [section(view)]
        return view

    def _close_preview(self) -> None:
        self._release_preview()
        self._preview = {}

    def _release_preview(self) -> None:
        """Close what the preview panel shows: the data browser's query (and
        so the view its data came from), a table set (its table's query, then
        its view), or the view shown."""
        queries, self._queries = list(self._queries.values()), {}
        table_sets, self._table_sets = list(self._table_sets.values()), {}
        view, self._preview_view = self._preview_view, None
        for data in queries:
            data.close()
        for tables in table_sets:
            tables.close()
        if view is not None:
            view.close()

    def _release_views(self) -> None:
        """Close the views the explorer shows, the preview panel's and its
        tabs', without closing any widget: at the kernel's exit
        (``_close_views_at_exit``), when no message reaches the page."""
        self._release_preview()
        for widget in list(self._view_tabs.values()):
            widget._release()

    # --- The query in the preview panel, for query_result() and
    # on_query_change() ---

    def _shown_query(self) -> DataQuery | None:
        """The query the preview panel shows in the data browser, or None
        (closed, loading, or showing something else)."""
        preview = self._preview
        if preview.get("loading"):
            return None
        if preview.get("table_set"):
            # The table chosen's.
            tables = self._table_sets.get(preview.get("path"))
            return tables.query if tables is not None else None
        if not preview.get("query"):
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
                raise ValueError(f"{item.ctx.name} cannot be queried now")
            previous, current[0] = current[0], again
            previous.close()
            return again.data

        def close() -> None:
            current[0].close()

        key = item.ctx.location
        state = self._states.query(key)
        mode = state.mode if state is not None else "auto"
        limits = self._view_limits
        options = {
            "fetch": self._fetch_rows,
            "cut": lambda: current[0].more,
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

    def _table_set(
        self, view: TableSetView, viewer: Callable[[], View], item: _Detected
    ) -> TableSet:
        """The data browser's tables of ``view``, the view ``viewer`` gave of
        ``item``.

        Each table chosen is read by the view's ``loader`` (a ``QueryView`` it
        gives tells whether the rows are cut short, and is closed with the
        table's query). A reload views the item again with ``viewer`` and reads
        the table from that view, which replaces the previous one (closed), so
        a loader's data read with the view (e.g. a workbook's bytes) is read
        again too (``TableSet._load``). Its settings are remembered by the
        item's URL and the table's id, as a ``QueryView``'s by location, with
        the mode last chosen for it.
        """
        url = item.ctx.location.url
        limits = self._view_limits
        options = {
            "fetch": self._fetch_rows,
            "max_live_rows": limits.max_live_rows,
            "max_memory_rows": limits.max_memory_rows,
            "page_rows": limits.max_display_rows,
        }

        def make_query(table: str, load: Callable[[bool], Any]) -> DataQuery:
            key = f"{url}#{table}"
            state = self._states.query(key)
            mode = state.mode if state is not None else "auto"
            # The table's QueryView, if the loader gave one (its data cut
            # short or not: ``more``), closed once replaced or no longer shown.
            loaded: list[QueryView | None] = [None]
            # Whether the table was read: the next read is a reload.
            read = [False]

            def source() -> Any:
                data = load(read[0])
                read[0] = True
                if isinstance(data, QueryView):
                    previous, loaded[0] = loaded[0], data
                    if previous is not None:
                        previous.close()
                    return data.data
                return data

            def cut() -> bool:
                return loaded[0] is not None and loaded[0].more

            def close() -> None:
                if loaded[0] is not None:
                    loaded[0].close()

            table_options = {**options, "cut": cut, "on_close": close}
            try:
                return DataQuery(source, key, self._states, mode=mode, **table_options)
            except ValueError:
                if mode != "live":
                    raise
                # "live" chosen when the table was lazy, and no longer is:
                # read again from the same view, not a reload.
                read[0] = False
                return DataQuery(source, key, self._states, **table_options)

        return TableSet(view, make_query, viewer)

    def _table_set_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "table_set_open": show another table of the table set
        previewed (``TableSet.choose``)."""
        tables = self._table_sets.get(content.get("path"))
        if tables is None:
            return {"error": "the tables are no longer open; preview them again"}
        return tables.choose(content)

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
        tables: TableSet | None = None
        try:
            item, fmt = self._formats_of(path, content.get("format") or None)
            engine = content.get("engine", ...)
            key = self._view_engine(fmt, item.ctx.name, engine)
            viewer = self._viewer(fmt, item, key)
            view = viewer()
            title = _paths.basename(path)
            label = " · ".join(filter(None, [fmt.label, self._engine_label(key)]))
            if isinstance(view, QueryView):
                data = self._new_query(view, viewer, item)
                widget: DataExplorer | TableSetTab | ViewTab = DataExplorer._of_query(
                    data,
                    self._states,
                    data.key,
                    title=title,
                    label=label,
                    height="fill",
                )
            elif isinstance(view, TableSetView):
                tables = self._table_set(view, viewer, item)
                widget = TableSetTab(tables, title=title, label=label)
            else:
                widget = ViewTab(
                    section(view), title=title, label=label, on_close=view.close
                )
        except Exception as exc:
            if data is not None:
                data.close()
            if tables is not None:
                tables.close()
            if view is not None:
                view.close()
            return {"error": error_text(exc)}
        self._view_tabs[widget.model_id] = widget
        return {
            "model_id": widget.model_id,
            "title": title,
            "url": item.ctx.location.url,
        }

    def _view_tab_closed(self, model_id: str) -> None:
        """The tab of a "view_tab" closed: its widget is no longer kept, and
        closing it closes its view."""
        widget = self._view_tabs.pop(model_id, None)
        if widget is not None:
            widget.close()

    def _query_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer the data browser's requests ("query_rows", "query_check",
        "query_save", "query_reload", "query_mode") on the data previewed;
        for a table set's table, "path" also names the table (see
        ``table_set.query_path``)."""
        path, separator, table = content["path"].partition(SEPARATOR)
        if separator:
            tables = self._table_sets.get(path)
            if tables is None:
                return {"error": "the tables are no longer open; preview them again"}
            return tables.handle(content, table)
        data = self._queries.get(content["path"])
        if data is None:
            return {"error": "the data is no longer open; preview it again"}
        return data.handle(content) or {}

    def _menu_info(self, path: str) -> dict[str, Any]:
        """Answer "menu_info", the right-click menu's, or {"error"}:
        "formats", the names of those matching; "view", the best format and
        the engine viewing it ("Preview", "View in a new tab"; None if the
        engine chosen cannot); "views", each format and engine that can
        ("Preview as", "View in new tab as"); "recipes", the best format's
        load code ("Python code"), with their engine's label."""
        try:
            item = self._detect(path)
            formats = item.formats if item is not None else []
            recipes = self._supports.recipes(formats[0], item.ctx) if formats else []
        except Exception as exc:
            return {"error": error_text(exc)}
        view = None
        if formats and self._viewable(formats[0]):
            key = self._supports.engine_for(formats[0], self._engine or None)
            view = {"format": formats[0].name, "engine": key}
        return {
            "formats": [f.name for f in formats],
            "view": view,
            "views": [
                {
                    "format": f.name,
                    "engine": key,
                    "label": " ".join(
                        filter(
                            None,
                            [f.label, f"({self._engine_label(key)})" if key else ""],
                        )
                    ),
                }
                for f in formats
                for key in self._supports.viewers(f)
            ],
            # The frontend gets the packages' names, listed under the code.
            "recipes": [
                {
                    "title": r.title,
                    "engine": r.engine.label if r.engine is not None else "Python",
                    "packages": [p.package for p in r.requirements],
                    "code": r.code,
                }
                for r in recipes
            ],
        }
