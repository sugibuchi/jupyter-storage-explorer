"""StorageExplorer's data browser in the preview panel: the queries of
the views previewed and of table sets' tables, and their requests (a
mixin of the class)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._query.data_query import DataQuery, read_again
from jupyter_storage_explorer._query.table_set import SEPARATOR, TableSet
from jupyter_storage_explorer.views import (
    QueryView,
    TableSetView,
    View,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer._explorer.previews import _Detected
    from jupyter_storage_explorer.base import Location


def _layered_fetch(
    user: Callable[[Any, int, int], Any] | None,
    view_fetch: Callable[[], Callable[[Any, int, int], Any] | None],
) -> Callable[[Any, int, int], Any]:
    """The data browser's ``fetch`` of a view's data: the explorer's
    ``fetch_rows`` (the user's), then the view's ``fetch`` (an action's), the
    one of the view now shown, as a reload's may differ; None where neither
    reads, for the default (``DataQuery``)."""

    def fetch(lf: Any, offset: int, length: int) -> Any:
        for read in (user, view_fetch()):
            if read is not None and (df := read(lf, offset, length)) is not None:
                return df
        return None

    return fetch


class _ViewRead:
    """How the data browser reads its data: with ``load(again)``, which gives
    the data or a ``QueryView`` of it, e.g. a table set's loader. The
    ``QueryView`` given last, if any, tells whether its rows are cut short
    (``more``) and how to read them (``fetch``), and is closed once replaced
    or no longer shown. ``first``: a ``QueryView`` just viewed, whose data
    is read first rather than loaded twice."""

    def __init__(
        self, load: Callable[[bool], Any], first: QueryView | None = None
    ) -> None:
        self._load = load
        self._first = first
        self.loaded = first
        # Whether the data was read: the next read is a reload.
        self.read = False

    def source(self) -> Any:
        if self._first is not None and not self.read:
            self.read = True
            return self._first.data
        data = self._load(self.read)
        self.read = True
        if isinstance(data, QueryView):
            previous, self.loaded, self._first = self.loaded, data, None
            if previous is not None:
                previous.close()
            return data.data
        return data

    def rewind(self) -> None:
        """Make the next read the first again, of the same data: after a
        query that could not open with it."""
        self.read = False

    def cut(self) -> bool:
        return self.loaded is not None and self.loaded.more

    def view_fetch(self) -> Any:
        return self.loaded.fetch if self.loaded is not None else None

    def close(self) -> None:
        if self.loaded is not None:
            self.loaded.close()


class QueriesMixin:
    """The data browser in the preview panel: the query of a ``QueryView``
    or of a table set's table, its requests, and ``query_result()``'s
    changes."""

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
        if self._query_watch.changed(self._shown_query(), reloaded=reloaded):
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

        def load(_again: bool) -> QueryView:
            again = viewer()
            if not isinstance(again, QueryView):
                again.close()
                raise ValueError(f"{item.ctx.name} cannot be queried now")
            return again

        return self._data_query(item.ctx.location, _ViewRead(load, view))

    def _data_query(self, key: Location | str, reading: _ViewRead) -> DataQuery:
        """The data browser's query of what ``reading`` reads, its settings
        remembered under ``key``, with the mode last chosen for it."""
        state = self._states.query(key)
        mode = state.mode if state is not None else "auto"
        limits = self._view_limits
        options = {
            "fetch": _layered_fetch(self._fetch_rows, reading.view_fetch),
            "cut": reading.cut,
            "max_live_rows": limits.max_live_rows,
            "max_memory_rows": limits.max_memory_rows,
            "page_rows": limits.max_display_rows,
            "on_close": reading.close,
        }
        try:
            return DataQuery(reading.source, key, self._states, mode=mode, **options)
        except ValueError:
            if mode != "live":
                raise
            # "live" chosen when the data was lazy, and no longer is: read
            # again from the same view, not a reload.
            reading.rewind()
            return DataQuery(reading.source, key, self._states, **options)

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

        def make_query(table: str, load: Callable[[bool], Any]) -> DataQuery:
            return self._data_query(f"{url}#{table}", _ViewRead(load))

        return TableSet(view, make_query, viewer)

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
            self._reply(content, answer)
            self._query_changed(reloaded=read_again(content, answer))

        path, separator, _ = content["path"].partition(SEPARATOR)
        if kind == "table_set_open" or separator:
            tables = self._table_sets.get(path)
            if tables is None:
                reply({"error": "the tables are no longer open; preview them again"})
            else:
                self._loader.answer(tables, lambda: tables.answer(content), reply)
            return
        data = self._queries.get(path)
        if data is None:
            reply({"error": "the data is no longer open; preview it again"})
        else:
            self._loader.answer(data, lambda: data.handle(content) or {}, reply)
