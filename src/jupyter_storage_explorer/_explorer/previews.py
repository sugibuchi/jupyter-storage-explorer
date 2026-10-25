"""StorageExplorer's previews, views in tabs of their own and the right-click
menu's formats and code (a mixin of the class)."""

from __future__ import annotations

import atexit
import base64
import concurrent.futures
import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Any, NamedTuple

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text, explorers
from jupyter_storage_explorer._explorer.table_set_tab import TableSetTab
from jupyter_storage_explorer._explorer.view_tab import ViewTab
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.table_set import SEPARATOR, TableSet
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    DataFormat,
    ItemContext,
    MediaView,
    QueryView,
    TableSetView,
    TableView,
    View,
    ViewWithChoice,
    ViewWithPrompt,
)
from jupyter_storage_explorer.formats.base import matching_formats
from jupyter_storage_explorer.formats.python import PythonEngine

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import EllipsisType

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer._explorer.supports import Recipe

log = logging.getLogger(__name__)


# How long a click's detection is reused: long enough for its menu or preview,
# short enough that files changed elsewhere show on the next click.
_DETECTED_SECONDS = 5.0

# What the preview panel or a view tab shows instead of a view: a notice
# ("again": with a button previewing the item again) or an error.
_LOADING = {"kind": "notice", "text": "Loading…"}


def _not_viewed(verb: str) -> dict[str, Any]:
    """What shows that the user cancelled a prompt."""
    return {"kind": "notice", "text": f"Not {verb}", "again": verb == "previewed"}


class _Detected(NamedTuple):
    """An item of the storage shown with a location, as formats and supports
    are given it, and the formats it matches, best first (see
    ``PreviewsMixin._detection``)."""

    ctx: ItemContext
    formats: list[DataFormat]


class _Viewer:
    """Views an item as a format with an engine, each time it is called: the
    first time with the context it was detected with; later (the data
    browser's reload) with one read again, so the view is of the item as it
    is now. The answers given to its prompts (``ViewWithPrompt``) are kept,
    and given again to those of later views, so a reload asks nothing."""

    def __init__(self, view: Callable[[bool], View]) -> None:
        # The support's view, of the context read again if True.
        self._view = view
        self._viewed = False
        self.answers: list[Any] = []

    def __call__(self) -> View:
        view = self._view(self._viewed)
        self._viewed = True
        for value in self.answers:
            if not isinstance(view, ViewWithPrompt):
                break
            view = _answered(view, value)
        return view

    def answer(self, prompt: ViewWithPrompt, value: Any) -> View:
        """The view of the user's answer to ``prompt``, one of this viewer's,
        kept for later views."""
        view = _answered(prompt, value)
        self.answers.append(value)
        return view


def _answered(prompt: ViewWithPrompt, value: Any) -> View:
    """The view ``prompt`` makes of ``value``, closing the prompt with it: the
    prompt's ``on_close`` may release what the view reads. The prompt is
    closed at once if that fails."""
    try:
        view = prompt.answer(value)
    except Exception:
        prompt.close()
        raise
    view.on_close(lambda _view: prompt.close())
    return view


class _Asking(NamedTuple):
    """A prompt shown, waiting for the user's answer: the viewer and item it
    came from, which view its answer, and its id in what the frontend
    shows, so that an answer to a prompt no longer shown is ignored."""

    view: ViewWithPrompt
    viewer: _Viewer
    item: _Detected
    id: int

    def close(self) -> None:
        self.view.close()

    def section(self) -> dict[str, Any]:
        return {**section(self.view), "prompt": self.id}


def _layered_fetch(
    user: Callable[[Any, int, int], Any] | None,
    view_fetch: Callable[[], Callable[[Any, int, int], Any] | None],
) -> Callable[[Any, int, int], Any]:
    """The data browser's ``fetch`` of a view's data: the explorer's
    ``fetch_rows`` (the user's), then the view's ``fetch`` (a support's), the
    one of the view now shown, as a reload's may differ; None where neither
    reads, for the default (``DataQuery``)."""

    def fetch(lf: Any, offset: int, length: int) -> Any:
        for read in (user, view_fetch()):
            if read is not None and (df := read(lf, offset, length)) is not None:
                return df
        return None

    return fetch


class _TableRead:
    """How the data browser reads a table set's table: with its loader,
    ``load(again)``, keeping the ``QueryView`` it gave, if any, which tells
    whether its rows are cut short (``more``) and how to read them
    (``fetch``), and is closed once replaced or no longer shown."""

    def __init__(self, load: Callable[[bool], Any]) -> None:
        self._load = load
        self.loaded: QueryView | None = None
        # Whether the table was read: the next read is a reload.
        self.read = False

    def source(self) -> Any:
        data = self._load(self.read)
        self.read = True
        if isinstance(data, QueryView):
            previous, self.loaded = self.loaded, data
            if previous is not None:
                previous.close()
            return data.data
        return data

    def cut(self) -> bool:
        return self.loaded is not None and self.loaded.more

    def view_fetch(self) -> Any:
        return self.loaded.fetch if self.loaded is not None else None

    def close(self) -> None:
        if self.loaded is not None:
            self.loaded.close()


class _Loaded(NamedTuple):
    """What a preview's load read (see ``PreviewsMixin._open_preview``): what
    shows it (None if nothing does) and the ``_preview`` to show."""

    shown: View | DataQuery | TableSet | _Asking | None
    preview: dict[str, Any]


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
    of the preview panel or a view tab); media bytes are base64-encoded. A
    prompt's function stays in the kernel, and a choice's values too: the
    frontend answers with a label."""
    data = {
        f.name: getattr(view, f.name)
        for f in dataclasses.fields(view)
        if not f.name.startswith("_") and f.name != "factory"
    }
    if isinstance(view, MediaView) and view.data is not None:
        data["data"] = base64.b64encode(view.data).decode("ascii")
    if isinstance(view, TableView):
        data["note"] = "; ".join(filter(None, [_rows_note(view), view.note]))
    if isinstance(view, ViewWithChoice):
        data["choices"] = list(view.choices)
    return {"kind": view.kind, **jsonable(data)}


def _recipe_engine(recipe: Recipe) -> str:
    """The key of a recipe's engine, as ``code_snippet`` names it: "python"
    for the built-in code (``PythonEngine``)."""
    return recipe.engine.key if recipe.engine is not None else PythonEngine.key


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

    def _detection(
        self, path: str, fs: AbstractFileSystem
    ) -> concurrent.futures.Future[_Detected | None]:
        """The item at ``path`` of ``fs`` and the formats matching it, as a
        future: None if it has no location, as it is then not treated as
        data. Called on the main thread; its result is waited for in a load's
        work (without a loop, it is there at once).

        A click asks for the same item several times, at once: its
        selection, its menu or its preview. On cloud storages each detection
        costs round trips (its info, a folder's listings, a file's first
        bytes). So a detection still running is shared, and the last item
        detected is kept for ``_DETECTED_SECONDS``. Refreshing, or a job's
        changes, forget both (``_invalidate_cache``). Otherwise the detection
        runs as a load (``_loader``)."""
        future: concurrent.futures.Future[_Detected | None] = (
            concurrent.futures.Future()
        )
        key = (id(fs), path)
        if self._detected is not None:
            detected_key, when, item = self._detected
            if detected_key == key and time.monotonic() - when < _DETECTED_SECONDS:
                future.set_result(item)
                return future
        running = self._detections_running.get(key)
        if running is not None:
            return running
        self._detections_running[key] = future
        detecting = (time.monotonic(), self._detections_forgotten)

        def work() -> _Detected | EllipsisType | None:
            try:
                item = self._detect_now(path, fs)
            except Exception as exc:
                future.set_exception(exc)
                return ...
            future.set_result(item)
            return item

        def done(item: _Detected | EllipsisType | None) -> None:
            if self._detections_running.get(key) is future:
                del self._detections_running[key]
            # Kept unless it failed, or the detections were forgotten meanwhile.
            if item is not ... and detecting[1] == self._detections_forgotten:
                self._detected = (key, detecting[0], item)

        self._loader.submit(work, done, done)
        return future

    def _detect_now(self, path: str, fs: AbstractFileSystem) -> _Detected | None:
        """The item at ``path`` of ``fs`` and its formats, read now: safe in
        a worker thread, as it touches no trait."""
        location = self._mappers.location_of(fs, path)
        if location is None:
            return None
        info = self._info(path, fs)
        children = self._ls(path, fs) if info.get("type") == "directory" else None
        ctx = ItemContext(
            location=location, fs=fs, path=path, info=info, children=children
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
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        engine: str | EllipsisType | None,
        chosen: str | None,
    ) -> str | None:
        """The engine viewing the item of ``ctx`` as ``fmt``: ``engine`` (a
        key; None for the built-in views) if given, "Preview as"; by default
        (...), the one chosen (``chosen``, ``_engine`` when the view was asked
        for), or the built-in views for formats it does not handle.
        ValueError if that cannot view it. Safe in a worker thread."""
        name = ctx.name
        viewers = self._supports.viewers(fmt, ctx)
        if engine is not ...:
            if engine not in viewers:
                with_ = self._engine_label(engine) or "the built-in views"
                raise ValueError(f"{name} cannot be viewed as {fmt.label} with {with_}")
            return engine
        try:
            return self._supports.engine_for(fmt, ctx, chosen)
        except LookupError:
            if not self._supports.installed(fmt):
                # Nothing installed views it: the engines come with plugins.
                raise ValueError(
                    f"{name} cannot be viewed as {fmt.label}: no library viewing "
                    f"it is installed, e.g. pip install "
                    f'"jupyter-storage-explorer[polars]"'
                ) from None
            if not viewers:
                # The supports installed refuse it, e.g. on a storage their
                # libraries cannot read.
                raise ValueError(
                    f"{name} cannot be viewed as {fmt.label} where it is stored "
                    f"with the libraries installed"
                ) from None
            raise ValueError(
                f"{name} cannot be viewed as {fmt.label} with "
                f"{self._engine_label(chosen)}: choose another engine in "
                f'"Preview as"'
            ) from None

    def _viewable(self, fmt: DataFormat, ctx: ItemContext) -> bool:
        """Whether the item of ``ctx`` can be viewed as ``fmt`` with the
        engine chosen (or the built-in views): the Preview button's, and the
        menu's. On the main thread: a support failing to tell is logged, and
        offers nothing."""
        try:
            self._supports.engine_for(fmt, ctx, self._engine or None)
        except LookupError:
            return False
        except Exception:
            log.exception("Telling whether %s can be viewed failed", ctx.name)
            return False
        return True

    def _viewer(
        self,
        fmt: DataFormat,
        item: _Detected,
        engine: str | None,
        action: str | None = None,
    ) -> _Viewer:
        """Views ``item`` as ``fmt`` with ``engine`` (a key; None for the
        built-in views; see ``_view_engine``), by its view ``action`` if
        named, each time it is called: on the storage it is on (its
        context's), also after switching storages; a context read again
        (``_refreshed``) after the first time."""
        limits = self._view_limits

        def view(again: bool) -> View:
            ctx = self._refreshed(fmt, item.ctx) if again else item.ctx
            return self._supports.view(fmt, ctx, limits, engine, action)

        return _Viewer(view)

    def _refreshed(self, fmt: DataFormat, ctx: ItemContext) -> ItemContext:
        """``ctx`` with the item's info and listing read again, on its own
        filesystem, without fsspec's cached listings: what a reload views. Its
        format is checked again (which refreshes what ``fmt`` keeps of it, e.g.
        a Parquet dataset's layout); ValueError if it no longer matches, or
        the item is gone. Safe in a worker thread: it leaves the explorer's
        detections (``_detected``) to the main thread."""
        ctx.fs.invalidate_cache(ctx.path)
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

    def _open_preview(
        self,
        path: str,
        format: str | None = None,
        engine: str | EllipsisType | None = ...,
        action: str | None = None,
    ) -> None:
        """Preview the file or directory at ``path`` in the preview panel: the
        data browser for a ``QueryView``, a ``TableSetView``'s tables, else
        the view's section (see ``_show``).

        ``format`` names one of the formats matching it (e.g. "text" for a JSON
        file); by default the best match is used. ``engine`` (a key; None for
        the built-in views) views it instead of the one chosen (see
        ``_view_engine``). ``action`` names the engine's view action; by
        default its first doing the item.

        The reads (the item's detection, its view, the data browser's first
        rows) run in a worker thread (``_loader``): the panel shows "loading"
        meanwhile, and the kernel stays free. Another preview, or closing the
        panel, cancels a preview still loading: what it read is closed.
        """
        if self._preview_load is not None:
            self._preview_load.cancel()
        base = {
            "path": path,
            "name": _paths.basename(path),
            "format": None,
            "engine": None,
            "engine_label": "",
            "action": action,
            "sections": [],
            "error": "",
        }
        # Shown while the (possibly remote) reads run.
        self._preview = {**base, "loading": True}
        # What the worker needs of the explorer, as it is now: the storage
        # shown and the engine chosen may change while it reads.
        chosen = self._engine or None
        detection = self._detection(path, self._fs)

        def work() -> _Loaded:
            return self._read_preview(
                dict(base),
                detection=detection,
                format=format,
                engine=engine,
                action=action,
                chosen=chosen,
            )

        self._submit_preview(path, work)

    def _submit_preview(self, path: str, work: Callable[[], _Loaded]) -> None:
        """Run a preview's reads, ``work``, as a load, then show what it read
        in the panel: a preview of ``path``, or the view of a prompt's
        answer."""

        def done(loaded: _Loaded) -> None:
            # The previous preview's, closed once the new one is open.
            self._release_preview()
            shown = loaded.shown
            if isinstance(shown, DataQuery):
                self._queries[path] = shown
            elif isinstance(shown, TableSet):
                self._table_sets[path] = shown
            else:
                self._preview_view = shown
            self._preview = loaded.preview

        def discard(loaded: _Loaded) -> None:
            if loaded.shown is not None:
                loaded.shown.close()

        self._preview_load = self._loader.submit(work, done, discard)

    def _preview_answer(self, content: dict[str, Any]) -> None:
        """The user answered the prompt the preview panel shows (see
        ``ViewWithPrompt``): "value", the answer, or "cancel". The view of
        the answer is read as a preview is; cancelling shows nothing. Ignored
        if the panel no longer shows that prompt ("path", "prompt")."""
        asking, preview = self._preview_view, self._preview
        if (
            not isinstance(asking, _Asking)
            or preview.get("loading")
            or content.get("path") != preview.get("path")
            or content.get("prompt") != asking.id
        ):
            return
        self._preview_view = None
        if content.get("cancel"):
            asking.close()
            self._preview = {**preview, "sections": [_not_viewed("previewed")]}
            return
        base = {**preview, "sections": [], "error": ""}
        self._preview = {**base, "loading": True}
        value = content.get("value")
        self._submit_preview(
            preview["path"], lambda: self._read_answer(dict(base), asking, value)
        )

    def _read_answer(
        self, preview: dict[str, Any], asking: _Asking, value: Any
    ) -> _Loaded:
        """In a worker thread, as ``_read_preview``: fill ``preview`` with the
        view of ``value``, the answer to ``asking``."""
        shown: View | DataQuery | TableSet | _Asking | None = None
        try:
            view = asking.viewer.answer(asking.view, value)
            shown = view
            shown = self._show(view, asking.viewer, asking.item, preview)
        except Exception as exc:
            preview["error"] = error_text(exc)
            if shown is not None:
                shown.close()
            shown = None
        return _Loaded(shown, preview)

    def _read_preview(
        self,
        preview: dict[str, Any],
        *,
        detection: concurrent.futures.Future[_Detected | None],
        format: str | None,
        engine: str | EllipsisType | None,
        chosen: str | None,
        action: str | None = None,
        verb: str = "previewed",
    ) -> _Loaded:
        """In a worker thread, touching no trait: fill ``preview`` (see
        ``_open_preview``) with the item of ``detection`` (``_detection``'s),
        viewed with ``chosen`` the engine chosen, by its view ``action`` if
        named. Its errors say it cannot be ``verb``."""
        path = preview["path"]
        # What shows it: the view, else its query or tables, which own it, or
        # the prompt asking for it.
        shown: View | DataQuery | TableSet | _Asking | None = None
        try:
            item = detection.result()
            if item is None:
                raise ValueError(f"{path} has no URL, so it cannot be {verb}")
            formats = item.formats
            if format is not None:
                formats = [f for f in formats if f.name == format]
                if not formats:
                    raise ValueError(f"{preview['name']} cannot be {verb} as {format}")
            if formats:
                fmt = formats[0]
                preview["format"] = fmt.name
                key = self._view_engine(fmt, item.ctx, engine, chosen)
                preview["engine"] = key
                preview["engine_label"] = self._engine_label(key)
                viewer = self._viewer(fmt, item, key, action)
                shown = viewer()
                shown = self._show(shown, viewer, item, preview)
        except Exception as exc:
            preview["error"] = error_text(exc)
            # Nothing shows it: released at once.
            if shown is not None:
                shown.close()
            shown = None
        return _Loaded(shown, preview)

    def _show(
        self,
        view: View,
        viewer: _Viewer,
        item: _Detected,
        preview: dict[str, Any],
    ) -> View | DataQuery | TableSet | _Asking:
        """Set what ``preview`` shows of ``view``, which ``viewer`` gave of
        ``item``: "query" (the data browser's) for a ``QueryView``,
        "table_set" for a ``TableSetView``, else "sections", a prompt's
        with its id. Returns what then owns the view: its query, its tables,
        the prompt waiting for its answer, or the view. The view is closed if
        they cannot be made."""
        if isinstance(view, ViewWithPrompt):
            asking = _Asking(view, viewer, item, next(self._prompt_ids))
            preview["sections"] = [asking.section()]
            return asking
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

    def _release_preview(self, *, now: bool = False) -> None:
        """Close what the preview panel shows: the data browser's query (and
        so the view its data came from), a table set (its table's query, then
        its view), or the view shown; a preview still loading is cancelled.

        A query or table set is closed in its lane, after the requests still
        reading it (see ``_answer_query``); ``now``, at once, as the kernel
        exits."""
        load, self._preview_load = self._preview_load, None
        if load is not None:
            load.cancel()
        queries, self._queries = list(self._queries.values()), {}
        table_sets, self._table_sets = list(self._table_sets.values()), {}
        view, self._preview_view = self._preview_view, None
        for shown in [*queries, *table_sets]:
            if now:
                shown.close()
            else:
                self._loader.close_in_lane(shown, shown.close)
        if view is not None:
            view.close()

    def _release_views(self) -> None:
        """Close the views the explorer shows, the preview panel's and its
        tabs', without closing any widget: at the kernel's exit
        (``_close_views_at_exit``), when no message reaches the page."""
        self._release_preview(now=True)
        self._cancel_view_tab_loads()
        for widget in list(self._view_tabs.values()):
            widget._release(now=True)

    def _release_view_tabs(self) -> None:
        """Close the widgets of the explorer's view tabs, and cancel those
        loading: when it closes, and when the launcher shows it again after a
        page reload, which closed the tabs without telling the kernel."""
        self._cancel_view_tab_loads()
        tabs, self._view_tabs = list(self._view_tabs.values()), {}
        for widget in tabs:
            widget.close()

    def _cancel_view_tab_loads(self) -> None:
        """Cancel the view tabs' loads still running: what they read is
        closed when they end."""
        loads, self._view_tab_loads = list(self._view_tab_loads.values()), {}
        for load in loads:
            load.cancel()

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
            "fetch": _layered_fetch(self._fetch_rows, lambda: current[0].fetch),
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
            "max_live_rows": limits.max_live_rows,
            "max_memory_rows": limits.max_memory_rows,
            "page_rows": limits.max_display_rows,
        }

        def make_query(table: str, load: Callable[[bool], Any]) -> DataQuery:
            key = f"{url}#{table}"
            state = self._states.query(key)
            mode = state.mode if state is not None else "auto"
            reading = _TableRead(load)
            table_options = {
                **options,
                "fetch": _layered_fetch(self._fetch_rows, reading.view_fetch),
                "cut": reading.cut,
                "on_close": reading.close,
            }
            try:
                return DataQuery(
                    reading.source, key, self._states, mode=mode, **table_options
                )
            except ValueError:
                if mode != "live":
                    raise
                # "live" chosen when the table was lazy, and no longer is:
                # read again from the same view, not a reload.
                reading.read = False
                return DataQuery(reading.source, key, self._states, **table_options)

        return TableSet(view, make_query, viewer)

    # --- Views in tabs of their own ("View in a new tab"), which the
    # launcher's JupyterLab extension shows: a DataExplorer of the data for
    # a QueryView, else a ViewTab of the view ---

    def _view_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "view_tab": view ``path`` (as ``format``, else its best
        format) in a new widget, a ``DataExplorer``, a ``TableSetTab`` or a
        ``ViewTab``, kept until the tab closes ("view_tab_closed").

        Answers at once, {"load_id", "title", "url"} or {"error"}, so that
        the tab opens showing that it loads. The reads run in a worker thread
        (``_loader``), as a preview's; then {"type": "view_tab", "load_id"}
        is sent, with the widget's "model_id" or an "error". Closing the tab
        before cancels the load: what it read is closed.

        A prompt (``ViewWithPrompt``) is shown in a ``ViewTab`` first, sent
        as the view is, with "asking": the tab keeps waiting. The view of the
        answer is read as the first, then sent for the same "load_id": the
        tab shows its widget instead, and lets the prompt's go. The prompt's
        widget shows the errors after an answer, and that it was cancelled.
        """
        path = content.get("path")
        location = self._location_of(path)
        if location is None:
            return {"error": f"{path} has no URL, so it cannot be viewed"}
        load_id = f"view-{next(self._view_tab_ids)}"
        title = _paths.basename(path)
        base = {
            "path": path,
            "name": title,
            "format": None,
            "engine": None,
            "engine_label": "",
            "sections": [],
            "error": "",
        }
        format, engine = content.get("format") or None, content.get("engine", ...)
        action = content.get("action") or None
        # As for a preview: what the worker needs of the explorer, as it is now.
        chosen = self._engine or None
        detection = self._detection(path, self._fs)

        def work() -> _Loaded:
            return self._read_preview(
                dict(base),
                detection=detection,
                format=format,
                engine=engine,
                action=action,
                chosen=chosen,
                verb="viewed",
            )

        self._submit_view_tab(load_id, title, work)
        return {"load_id": load_id, "title": title, "url": location.url}

    def _submit_view_tab(
        self,
        load_id: str,
        title: str,
        work: Callable[[], _Loaded],
        asked: ViewTab | None = None,
    ) -> None:
        """Run a view tab's reads, ``work``, as a load, then send what it
        read (see ``_view_tab_request``). ``asked``: the widget of the prompt
        whose answer is read, which shows the errors and a next prompt."""

        def done(loaded: _Loaded) -> None:
            self._view_tab_loads.pop(load_id, None)
            if isinstance(loaded.shown, _Asking):
                self._view_tab_ask(load_id, title, loaded, asked)
                return
            try:
                widget = self._view_tab_widget(loaded, title)
            except Exception as exc:
                discard(loaded, popped=True)
                if asked is not None:
                    asked._show({"kind": "error", "text": error_text(exc)})
                    return
                self.send(
                    {"type": "view_tab", "load_id": load_id, "error": error_text(exc)}
                )
                return
            self._view_tabs[widget.model_id] = widget
            self.send(
                {"type": "view_tab", "load_id": load_id, "model_id": widget.model_id}
            )

        def discard(loaded: _Loaded, popped: bool = False) -> None:
            if not popped:
                self._view_tab_loads.pop(load_id, None)
            if loaded.shown is not None:
                loaded.shown.close()

        load = self._loader.submit(work, done, discard)
        if not load.ended:  # without a loop, it has ended already
            self._view_tab_loads[load_id] = load

    def _view_tab_ask(
        self, load_id: str, title: str, loaded: _Loaded, asked: ViewTab | None
    ) -> None:
        """Show the prompt a view tab's load read, in the widget of the
        previous prompt, ``asked``, else in a new one sent to the tab."""
        asking = loaded.shown
        assert isinstance(asking, _Asking)
        widget = (
            asked
            if asked is not None
            else ViewTab(_LOADING, title=title, label=self._tab_label(loaded.preview))
        )

        def answered(content: dict[str, Any]) -> None:
            self._view_tab_answer(
                load_id,
                title,
                loaded.preview,
                asking=asking,
                widget=widget,
                content=content,
            )

        widget._show(asking.section(), on_close=asking.close, on_answer=answered)
        if asked is not None:
            return
        self._view_tabs[widget.model_id] = widget
        self.send(
            {
                "type": "view_tab",
                "load_id": load_id,
                "model_id": widget.model_id,
                "asking": True,
            }
        )

    def _view_tab_answer(
        self,
        load_id: str,
        title: str,
        preview: dict[str, Any],
        *,
        asking: _Asking,
        widget: ViewTab,
        content: dict[str, Any],
    ) -> None:
        """The user answered the prompt of a view tab, which ``widget``
        shows: read the view of the answer for the tab (see
        ``_view_tab_request``). Ignored if the widget no longer shows it."""
        if content.get("prompt") != asking.id or widget.view.get("prompt") != asking.id:
            return
        if content.get("cancel"):
            widget._show(_not_viewed("viewed"))
            asking.close()
            return
        # The load owns the prompt now: the widget no longer closes it.
        widget._show(_LOADING)
        base = {**preview, "sections": [], "error": ""}
        value = content.get("value")
        self._submit_view_tab(
            load_id,
            title,
            lambda: self._read_answer(dict(base), asking, value),
            asked=widget,
        )

    def _tab_label(self, preview: dict[str, Any]) -> str:
        """A view tab's label: the format's, and the engine's."""
        fmt = next(f for f in self._formats if f.name == preview["format"])
        return " · ".join(filter(None, [fmt.label, preview["engine_label"]]))

    def _view_tab_widget(
        self, loaded: _Loaded, title: str
    ) -> DataExplorer | TableSetTab | ViewTab:
        """The widget of a view tab's load (see ``_view_tab_request``), on
        the main thread; ValueError if the item could not be viewed."""
        preview, shown = loaded.preview, loaded.shown
        if preview["error"]:
            raise ValueError(preview["error"])
        if shown is None:
            raise ValueError(f"{title} cannot be viewed in any format")
        label = self._tab_label(preview)
        if isinstance(shown, DataQuery):
            return DataExplorer._of_query(
                shown, self._states, shown.key, title=title, label=label, height="fill"
            )
        if isinstance(shown, TableSet):
            return TableSetTab(shown, title=title, label=label)
        return ViewTab(
            preview["sections"][0], title=title, label=label, on_close=shown.close
        )

    def _view_tab_closed(self, content: dict[str, Any]) -> None:
        """The tab of a "view_tab" closed: its widget ("model_id") is no
        longer kept, and closing it closes its view; a load still running
        ("load_id") is cancelled."""
        load = self._view_tab_loads.pop(content.get("load_id"), None)
        if load is not None:
            load.cancel()
        widget = self._view_tabs.pop(content.get("model_id"), None)
        if widget is not None:
            widget.close()

    def _answer_query(self, content: dict[str, Any]) -> None:
        """Answer the data browser's requests ("query_rows", "query_check",
        "query_save", "query_reload", "query_mode") on the data previewed,
        and "table_set_open" (``TableSet.choose``); for a table set's table,
        "path" also names the table (see ``table_set.query_path``).

        They may read the data (e.g. a Spark job for each page), so they run
        in a worker thread (``_loader``), in the lane of their query or
        tables: in order, never two at once on the same data. Then, on the
        main thread, the reply is sent, and the ``on_query_change`` functions
        are told if ``query_result()`` changed: after the reply, so the
        widget does not wait for them."""
        kind = content["type"]

        def reply(answer: dict[str, Any]) -> None:
            self.send({"type": "reply", "rid": content["rid"], **answer})
            self._query_changed(
                reloaded=kind == "query_reload" and "error" not in answer
            )

        path, separator, table = content["path"].partition(SEPARATOR)
        if kind == "table_set_open" or separator:
            tables = self._table_sets.get(path)
            if tables is None:
                reply({"error": "the tables are no longer open; preview them again"})
            elif kind == "table_set_open":
                self._loader.answer(tables, lambda: tables.choose(content), reply)
            else:
                self._loader.answer(
                    tables, lambda: tables.handle(content, table), reply
                )
            return
        data = self._queries.get(path)
        if data is None:
            reply({"error": "the data is no longer open; preview it again"})
        else:
            self._loader.answer(data, lambda: data.handle(content) or {}, reply)

    def _answer_menu_info(self, content: dict[str, Any]) -> None:
        """Answer "menu_info", the right-click menu's (see ``_menu_info``).
        The item's detection and its recipes may read it (e.g. a CSV file's
        separator), so they run as a load (``_loader``), sharing the click's
        detection (``_detection``); the reply is made on the main thread."""
        detection = self._detection(content["path"], self._fs)
        engines = self._code_engines
        chosen = self._engine or None

        def work() -> dict[str, Any]:
            try:
                item = detection.result()
                if item is None:
                    return self._menu_info([], [], None, chosen)
                formats = item.formats
                recipes = (
                    self._supports.recipes(formats[0], item.ctx)
                    if formats and engines != frozenset()
                    else []
                )
                # Only the engines code_snippet names, if it names some.
                if engines is not None:
                    recipes = [r for r in recipes if _recipe_engine(r) in engines]
                return self._menu_info(formats, recipes, item.ctx, chosen)
            except Exception as exc:
                return {"error": error_text(exc)}

        def reply(answer: dict[str, Any]) -> None:
            self.send({"type": "reply", "rid": content["rid"], **answer})

        self._loader.submit(work, reply, reply)

    def _view_entries(
        self, fmt: DataFormat, key: str | None, names: list[str]
    ) -> list[dict[str, Any]]:
        """The entries of "Preview as" for an item viewed as ``fmt`` with the
        engine of ``key`` by its views ``names``: one, e.g. "CSV (Polars)";
        or, for several, one per view, by name, e.g. "CSV (Polars): Widget
        for CSV"."""
        engine = f"({self._engine_label(key)})" if key else ""
        label = " ".join(filter(None, [fmt.label, engine]))
        if len(names) <= 1:
            return [{"format": fmt.name, "engine": key, "label": label}]
        return [
            {
                "format": fmt.name,
                "engine": key,
                "action": name,
                "label": f"{label}: {name}",
            }
            for name in names
        ]

    def _menu_info(
        self,
        formats: list[DataFormat],
        recipes: list[Recipe],
        ctx: ItemContext | None,
        chosen: str | None,
    ) -> dict[str, Any]:
        """The reply to "menu_info" for the item of ``ctx`` matching
        ``formats``, best first, with ``recipes`` the best format's, and
        ``chosen`` the engine chosen: "formats", the names of those matching;
        "view", the best format and the engine viewing it ("Preview", "View
        in a new tab"; None if the engine chosen cannot); "views", each
        format and engine that can ("Preview as", "View in new tab as"),
        each of the engine's views by name if it has several;
        "recipes", the load code ("Python code"), with their engine's label,
        or the error of a support's. Safe in a worker thread."""
        view = None
        if formats and ctx is not None:
            try:
                key = self._supports.engine_for(formats[0], ctx, chosen)
            except LookupError:
                pass
            else:
                view = {"format": formats[0].name, "engine": key}
        return {
            "formats": [f.name for f in formats],
            "view": view,
            "views": [
                view
                for f in formats
                if ctx is not None
                for key, names in self._supports.views_by_engine(f, ctx).items()
                for view in self._view_entries(f, key, names)
            ],
            # The frontend gets the packages' names, listed under the code.
            "recipes": [
                {
                    "title": r.title,
                    "engine": r.engine.label if r.engine is not None else "Python",
                    "packages": [p.package for p in r.requirements],
                    "code": r.code,
                    **({"error": r.error} if r.error else {}),
                }
                for r in recipes
            ],
        }
