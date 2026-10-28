"""StorageExplorer's previews (a mixin of the class): items detected, viewed
and shown in the preview panel. The data browser's queries, view tabs and
the right-click menu build on them, in queries.py, view_tabs.py and
item_menu.py."""

from __future__ import annotations

import atexit
import base64
import concurrent.futures
import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Any, NamedTuple

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._errors import error_text
from jupyter_storage_explorer._explorer.common import explorers
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.table_set import TableSet
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.formats.base import matching_formats
from jupyter_storage_explorer.views import (
    JupyterWidgetView,
    MediaView,
    QueryView,
    TableSetView,
    TableView,
    View,
    ViewWithChoice,
    ViewWithPrompt,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import EllipsisType

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats import DataFormat

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


def _with_bases(found: list[DataFormat], formats: list[DataFormat]) -> list[DataFormat]:
    """``found`` and, after them, those of ``formats`` that are base classes
    of theirs, e.g. Text for a CSV file: the item can be viewed as those too,
    in "Preview as", which lists a view under its own format."""
    by_class = {type(f): f for f in formats}
    result = list(found)
    for fmt in found:
        for cls in type(fmt).__mro__[1:]:
            base = by_class.get(cls)
            if base is not None and base not in result:
                result.append(base)
    return result


class _Detected(NamedTuple):
    """An item of the storage shown with a location, as formats and actions
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
        # The action's view, of the context read again if True.
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


class _Loaded(NamedTuple):
    """What a preview's load read (see ``PreviewsMixin._open_preview``): what
    shows it (None if nothing does) and the ``_preview`` to show."""

    shown: View | DataQuery | TableSet | _Asking | None
    preview: dict[str, Any]


def _empty_preview(path: str, action: int | None) -> dict[str, Any]:
    """A preview of ``path``, or a view tab's, before its reads fill it in
    (see ``PreviewsMixin._read_preview``)."""
    return {
        "path": path,
        "name": _paths.basename(path),
        "format": None,
        "engine": None,
        "engine_label": "",
        "action": action,
        "sections": [],
        "error": "",
    }


def _failed(
    preview: dict[str, Any],
    shown: View | DataQuery | TableSet | _Asking | None,
    exc: Exception,
    what: str,
) -> _Loaded:
    """A preview's load whose reads raised ``exc``: ``preview`` with the
    error, logged as the item ``what`` (e.g. "cannot be previewed"), and
    ``shown``, what they made so far, closed."""
    preview["error"] = error_text(exc)
    # The user sees the error; its traceback is for DEBUG.
    log.warning(
        "%s %s: %s",
        preview["path"],
        what,
        preview["error"],
        exc_info=log.isEnabledFor(logging.DEBUG),
    )
    # Nothing shows it: released at once.
    if shown is not None:
        shown.close()
    return _Loaded(None, preview)


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
        if not f.name.startswith("_") and f.name not in ("factory", "widget")
    }
    if isinstance(view, JupyterWidgetView):
        # The page renders the widget's model, which its kernel already sent.
        data["model_id"] = view.widget.model_id
    if isinstance(view, MediaView) and view.data is not None:
        data["data"] = base64.b64encode(view.data).decode("ascii")
    if isinstance(view, TableView):
        data["note"] = "; ".join(filter(None, [_rows_note(view), view.note]))
    if isinstance(view, ViewWithChoice):
        data["choices"] = list(view.choices)
    return {"kind": view.kind, **jsonable(data)}


def action_id(value: Any) -> int | None:
    """The view action's id a request of the page gives (``Action.id``), or
    None for the engine's default: the page's values are taken only if they
    are what it sends, an integer."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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
    browser for a ``QueryView`` (see ``QueriesMixin``); the items' detection,
    which view tabs and the right-click menu share; and the Preview button's
    format (``_selected_format``)."""

    def _show_selected_format(self) -> None:
        """Set ``_selected_format`` for the items selected: the item's best
        format, if the engine chosen can view it (the Preview button).

        The item's detection may read it, so it runs as a load, sharing the
        click's detection (``_detection``): until it ends, the frontend
        offers no Preview for the item. A later selection cancels it."""
        if self._selection_load is not None:
            self._selection_load.cancel()
            self._selection_load = None
        selected = list(self._selected)
        if len(selected) != 1:
            self._selected_format = {}
            return
        path = selected[0]
        detection = self._detection(path, self._fs)

        def work() -> _Detected | None:
            try:
                return detection.result()
            except Exception:
                return None  # detection is best-effort; a failure just means no preview

        def done(item: _Detected | None) -> None:
            formats = item.formats if item is not None else []
            viewable = bool(formats) and self._viewable(formats[0], item.ctx)
            self._selected_format = {
                "path": path,
                "format": formats[0].name if viewable else "",
            }

        self._selection_load = self._loader.submit(work, done, lambda _: None)

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
        started = time.monotonic()
        location = self._mappers.location_of(fs, path)
        if location is None:
            log.debug("Detected %s: no location, so no formats", path)
            return None
        info = self._info(path, fs)
        children = self._ls(path, fs) if info.get("type") == "directory" else None
        ctx = ItemContext(
            location=location, fs=fs, path=path, info=info, children=children
        )
        found = matching_formats(ctx, formats=self._formats)
        detected = _Detected(ctx, _with_bases(found, self._formats))
        log.debug(
            "Detected %s in %.3f s: %s",
            path,
            time.monotonic() - started,
            ", ".join(f.name for f in detected.formats) or "no format",
        )
        return detected

    def _engine_label(self, key: str | None) -> str:
        """The label of the engine of ``key``, e.g. "Polars"; "" for the
        built-in views (None)."""
        if key is None:
            return ""
        engine = next((e for e in self._actions.engines if e.key == key), None)
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
        viewers = self._actions.viewers(fmt, ctx)
        if engine is not ...:
            if engine not in viewers:
                with_ = self._engine_label(engine) or "the built-in views"
                raise ValueError(f"{name} cannot be viewed as {fmt.label} with {with_}")
            return engine
        try:
            return self._actions.engine_for(fmt, ctx, chosen)
        except LookupError:
            if not self._actions.installed(fmt):
                # Nothing installed views it: the engines come with plugins.
                raise ValueError(
                    f"{name} cannot be viewed as {fmt.label}: no library viewing "
                    f"it is installed, e.g. pip install "
                    f'"jupyter-storage-explorer[polars]"'
                ) from None
            if not viewers:
                # The actions installed refuse it, e.g. on a storage their
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
        menu's. On the main thread: a check failing to tell is logged, and
        offers nothing."""
        try:
            self._actions.engine_for(fmt, ctx, self._engine or None)
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
        action: int | None = None,
    ) -> _Viewer:
        """Views ``item`` as ``fmt`` with ``engine`` (a key; None for the
        built-in views; see ``_view_engine``), by its view of id ``action``
        if given, each time it is called: on the storage it is on (its
        context's), also after switching storages; a context read again
        (``_refreshed``) after the first time."""
        limits = self._view_limits

        def view(again: bool) -> View:
            started = time.monotonic()
            ctx = self._refreshed(fmt, item.ctx) if again else item.ctx
            made = self._actions.view(fmt, ctx, limits, engine, action)
            log.info(
                "%s %s as %s with %s: %s in %.2f s",
                "Viewed again" if again else "Viewed",
                ctx.path,
                fmt.name,
                engine or "the built-in views",
                type(made).__name__,
                time.monotonic() - started,
            )
            return made

        return _Viewer(view)

    def _refreshed(self, fmt: DataFormat, ctx: ItemContext) -> ItemContext:
        """``ctx`` with the item's info and listing read again, on its own
        filesystem, without fsspec's cached listings: what a reload views. Its
        format is checked again (which refreshes what ``fmt`` keeps of it, e.g.
        a Parquet dataset's layout); ValueError if it no longer matches, or
        the item is gone. Safe in a worker thread: it leaves the explorer's
        detections (``_detected``) to the main thread."""
        self._drop_cached(ctx.path, ctx.fs)
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
        action: int | None = None,
    ) -> None:
        """Preview the file or directory at ``path`` in the preview panel: the
        data browser for a ``QueryView``, a ``TableSetView``'s tables, else
        the view's section (see ``_show``).

        ``format`` names one of the formats matching it (e.g. "text" for a JSON
        file); by default the best match is used. ``engine`` (a key; None for
        the built-in views) views it instead of the one chosen (see
        ``_view_engine``). ``action`` is the id of the engine's view action;
        by default its first doing the item.

        The reads (the item's detection, its view, the data browser's first
        rows) run in a worker thread (``_loader``): the panel shows "loading"
        meanwhile, and the kernel stays free. Another preview, or closing the
        panel, cancels a preview still loading: what it read is closed.
        """
        if self._preview_load is not None:
            self._preview_load.cancel()
        base = _empty_preview(path, action)
        # Shown while the (possibly remote) reads run.
        self._preview = {**base, "loading": True}
        self._submit_preview(path, self._preview_work(base, format, engine, action))

    def _preview_work(
        self,
        base: dict[str, Any],
        format: str | None,
        engine: str | EllipsisType | None,
        action: int | None,
        verb: str = "previewed",
    ) -> Callable[[], _Loaded]:
        """The reads of a preview, or of a view tab, as a load's work: they
        fill a copy of ``base`` (see ``_read_preview``). What they need of
        the explorer is taken now, as the storage shown and the engine chosen
        may change while they run."""
        chosen = self._engine or None
        detection = self._detection(base["path"], self._fs)

        def work() -> _Loaded:
            return self._read_preview(
                dict(base),
                detection=detection,
                format=format,
                engine=engine,
                action=action,
                chosen=chosen,
                verb=verb,
            )

        return work

    def _submit_preview(self, path: str, work: Callable[[], _Loaded]) -> None:
        """Run a preview's reads, ``work``, as a load, then show what it read
        in the panel: a preview of ``path``, or the view of a prompt's
        answer."""

        def done(loaded: _Loaded) -> None:
            # The previous preview's, closed once the new one is open.
            self._release_preview()
            shown = loaded.shown
            if isinstance(shown, (DataQuery, TableSet)):
                self._preview_data = (path, shown)
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
            shown = asking.viewer.answer(asking.view, value)
            shown = self._show(shown, asking.viewer, asking.item, preview)
        except Exception as exc:
            return _failed(
                preview, shown, exc, "cannot be viewed with the answer given"
            )
        return _Loaded(shown, preview)

    def _read_preview(
        self,
        preview: dict[str, Any],
        *,
        detection: concurrent.futures.Future[_Detected | None],
        format: str | None,
        engine: str | EllipsisType | None,
        chosen: str | None,
        action: int | None = None,
        verb: str = "previewed",
    ) -> _Loaded:
        """In a worker thread, touching no trait: fill ``preview`` (see
        ``_open_preview``) with the item of ``detection`` (``_detection``'s),
        viewed with ``chosen`` the engine chosen, by its view of id ``action``
        if given. Its errors say it cannot be ``verb``."""
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
            return _failed(preview, shown, exc, f"cannot be {verb}")
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
        data, self._preview_data = self._preview_data, None
        view, self._preview_view = self._preview_view, None
        if data is not None:
            shown = data[1]
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
