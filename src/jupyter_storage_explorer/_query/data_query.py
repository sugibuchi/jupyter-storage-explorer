"""One dataset open in the data browser (``DataQuery``): its modes, pages of
rows and requests; and ``fetch_rows``, how a page is read."""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING, Any

import narwhals as nw

from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.filters import (
    build_query,
    check_filter,
    columns_info,
    normalize_settings,
)
from jupyter_storage_explorer._query.settings import QuerySettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer._explorer.states import ExplorerStates
    from jupyter_storage_explorer.base import Location

log = logging.getLogger(__name__)

MODES = ("auto", "live", "memory")

# The data browser's requests, by "type" (see DataQuery.handle).
REQUESTS = frozenset(
    {"query_rows", "query_check", "query_save", "query_reload", "query_mode"}
)


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def fetch_rows(lf: nw.LazyFrame, offset: int, length: int) -> nw.DataFrame:
    """Read rows of a query's result, for the data browser: a page of its
    table, or the first rows when the data opens.

    The default of ``DataExplorer``'s and ``StorageExplorer``'s
    ``fetch_rows``, which replace it for every read of lazy data (rows held
    in memory are sliced), and fall back to it for reads they return None
    for; a view's ``fetch`` comes between them (``QueryView``). polars and
    DuckDB skip the rows before ``offset`` themselves. Dask reads partition
    by partition until it has the rows (narwhals' ``head`` would read every
    partition), and sorted data in one pass. Other libraries (e.g. Spark)
    have no portable way to skip rows, so all rows up to ``offset + length``
    are read and the first ones dropped.

    Parameters
    ----------
    lf : narwhals.LazyFrame
        The query: the data (or the rows in memory) with the browser's
        filters, sort order and hidden columns applied.
    offset : int
        The first row to read.
    length : int
        The most rows to read.

    Returns
    -------
    narwhals.DataFrame
        Rows ``offset`` to ``offset + length`` of the result, or fewer at its
        end. Pages are separate queries, so they line up only if the library
        gives the result in the same order each time.

    Examples
    --------
    Spark (3.4 and later) can skip rows with ``offset``. Its order is stable
    only when sorted by columns that tell all rows apart.

    >>> import narwhals as nw
    >>> def spark_offset(lf, offset, length):
    ...     page = lf.to_native().offset(offset).limit(length)
    ...     return nw.from_native(page).collect()
    >>> DataExplorer(spark.table("sales"), fetch_rows=spark_offset)
    """
    native = lf.to_native()
    if lf.implementation.is_polars():
        return nw.from_native(native.slice(offset, length).collect())
    if lf.implementation.is_duckdb():
        return nw.from_native(native.limit(length, offset)).collect()
    if lf.implementation.is_dask():
        return _dask_rows(native, offset, length)
    df = lf.head(offset + length).collect()
    return df.tail(max(0, len(df) - offset))


def _dask_sorted(native: Any) -> bool:
    """Whether a Dask DataFrame is sorted (a ``SortValues`` in its
    expression): False if the expressions cannot tell, e.g. an older Dask's."""
    try:
        return any(type(e).__name__ == "SortValues" for e in native.expr.walk())
    except Exception:
        return False


def _dask_rows(native: Any, offset: int, length: int) -> nw.DataFrame:
    """Rows ``offset`` to ``offset + length`` of a Dask DataFrame, computing
    its partitions in order until there are enough: the first page of a
    large file reads its first block, not all of them.

    Sorted data is read in one pass instead, Dask's ``head`` of every
    partition (the smallest rows of each, then of those): computed one by
    one, each partition would sort all the data again."""
    needed = offset + length
    if _dask_sorted(native):
        rows = native.head(needed, npartitions=-1)
        return nw.from_native(rows, eager_only=True)[offset:needed]
    have, parts = 0, []
    for i in range(native.npartitions):
        part = nw.from_native(native.partitions[i].compute(), eager_only=True)
        parts.append(part)
        have += len(part)
        if have >= needed:
            break
    if not parts:
        return nw.from_native(native.head(0, npartitions=1), eager_only=True)
    df = nw.concat(parts) if len(parts) > 1 else parts[0]
    return df[offset:needed]


class DataQuery:
    """One dataset open in the data browser, answering its frontend's requests.

    ``source`` is the data, any dataframe narwhals supports, or a function
    returning it, called again to reload the data (e.g. a polars ``scan_*``,
    to read a file again). Settings, and the mode the user chose, are
    remembered in ``states`` under ``key`` (e.g. the data's URL), at each
    change: they are those of the most recently used datasets (see
    ``ExplorerStates``). The frontend's requests are "query_rows",
    "query_check", "query_save", "query_reload" and "query_mode" (see
    static/query.js).

    Queries run in one of two modes, switched between in the data browser:

    - "live": on the source itself, e.g. a polars LazyFrame or a Spark
      DataFrame, each query reading the data again, a page at a time with
      ``fetch`` (``fetch_rows`` by default). Results give at most
      ``max_memory_rows`` rows: libraries that cannot skip rows (e.g. Spark)
      read all rows before each page.
    - "memory": on rows read into memory once, at most ``max_memory_rows``
      (the first ones; filters and sorting then apply to those only), queried
      in the data's own library: eager data as it is (e.g. pandas), lazy data
      in the library narwhals collects it into (polars for polars, PyArrow
      for DuckDB and Spark). So filters behave as ``result()``'s, which run
      on the data itself, and no other library is needed.

    ``mode`` chooses the mode to start in. "auto" (the default) is "live" for
    lazy data, unless it has at most ``max_live_rows`` rows: the first query
    reads them all anyway, so they are kept in memory. Eager data (pandas,
    PyArrow, polars DataFrames, ...) is always queried in memory, so "live"
    raises ValueError for it. When all the data is in memory, the mode cannot
    be switched.

    Every read of lazy data, the first rows when opening and each live page,
    goes through ``fetch`` if given (an explorer's: its ``fetch_rows``, the
    user's, then the view's ``fetch``, an action's), then ``fetch_rows``,
    the default: the first giving rows reads them.

    ``cut``, if given, tells whether the data the source gave holds only the
    first part of the item's: eager data its first rows (e.g. read with
    pandas, which reads eagerly), which the browser counts as it does rows
    read into memory; lazy data, e.g. a file's first bytes, which the browser
    says in either mode (``partial``), as switching to live reads no more.

    ``on_close`` is called by ``close()``, once nothing shows the query any
    more, to release what its data holds (the explorer closes the views
    its data came from).
    """

    def __init__(
        self,
        source: Any,
        key: Location | str,
        states: ExplorerStates,
        *,
        mode: str = "auto",
        max_live_rows: int = 5000,
        max_memory_rows: int = 100_000,
        page_rows: int = 100,
        fetch: Callable[[nw.LazyFrame, int, int], nw.DataFrame | None] | None = None,
        cut: Callable[[], bool] | None = None,
        on_close: Callable[[], object] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        self.scan: Callable[[], Any] = source if callable(source) else lambda: source
        self.on_close = on_close
        self.key = key
        self.states = states
        self.max_live_rows = max_live_rows
        self.max_memory_rows = max_memory_rows
        # Rows of a page of the browser's table.
        self.page_rows = max(1, page_rows)
        self.fetch = fetch
        self.cut = cut
        # The mode asked for, by the caller or the user: reloading starts in it.
        self.requested = mode
        self._open(mode)

    def close(self) -> None:
        """Call ``on_close``, the first time only."""
        on_close, self.on_close = self.on_close, None
        if on_close is not None:
            on_close()

    # --- Modes ---

    def _open(self, mode: str) -> None:
        """Read the data (again) and set up queries in ``mode`` ("auto", "live" or "memory").

        Sets ``implementation`` (the data's library), ``source`` (the lazy
        data, or None for eager data), ``mode``,
        ``lf`` (what queries run on), ``schema``, ``memory`` ({"rows",
        "cut"}: rows held and whether there are more, or None in live mode),
        ``partial`` (lazy data holding only the item's first part, see
        ``cut``) and ``fixed`` (why the mode cannot be switched, or "").
        """
        native = self.scan()
        # Asked once the source has given the data: a reload's view may differ.
        cut_short = self.cut is not None and self.cut()
        data = nw.from_native(native)
        # The data as given (or as the function returned it), for ``result``.
        self.native = native
        # The data's own library (lazy data in memory may be in another, e.g.
        # DuckDB's in PyArrow) and type, e.g. "LazyFrame".
        self.implementation = data.implementation
        self.type_name = type(nw.to_native(native, pass_through=True)).__name__
        if isinstance(data, nw.DataFrame):
            if mode == "live":
                raise ValueError(
                    f"live mode needs lazy data (e.g. a polars LazyFrame, DuckDB "
                    f"or Spark); {data.implementation} dataframes are queried in "
                    f"memory"
                )
            self.source = None
            self.partial = False  # counted as rows in memory instead
            self._hold(data, cut=cut_short)
            self.fixed = "The data is a dataframe in memory."
            return
        self.source = data
        self.partial = cut_short
        if mode == "memory":
            self._load_memory()
        elif not self._fits_live_rows():
            self._go_live()

    def _read(self, lf: nw.LazyFrame, offset: int, length: int) -> nw.DataFrame:
        """Rows ``offset`` to ``offset + length`` of lazy data: every read of
        the source, the first rows when opening and the pages of live
        queries. By ``fetch``, else, where it gives None, ``fetch_rows``."""
        if (
            self.fetch is not None
            and (df := self.fetch(lf, offset, length)) is not None
        ):
            return df
        return fetch_rows(lf, offset, length)

    def _fits_live_rows(self) -> bool:
        """Keep the data in memory if it has at most ``max_live_rows`` rows."""
        head = self._read(self.source, 0, self.max_live_rows + 1)
        if len(head) > self.max_live_rows:
            return False
        self._hold(head, cut=False)
        # Live queries would read the same rows again: nothing to switch to.
        self.fixed = f"All {len(head):,} rows are in memory."
        return True

    def _load_memory(self) -> None:
        """Read the first ``max_memory_rows`` rows into memory, to query them there."""
        rows = self._read(self.source, 0, self.max_memory_rows + 1)
        cut = len(rows) > self.max_memory_rows
        self._hold(rows.head(self.max_memory_rows), cut=cut)

    def _hold(self, df: nw.DataFrame, *, cut: bool) -> None:
        """Query ``df`` in memory; ``cut``: the data has more rows."""
        self.mode = "memory"
        self.lf = df.lazy()
        self.schema = self.lf.collect_schema()
        self.memory = {"rows": len(df), "cut": cut}
        self.fixed = ""
        self._forget_result()

    def _go_live(self) -> None:
        self.mode = "live"
        self.lf = self.source
        self.schema = self.lf.collect_schema()
        self.memory = None
        self.fixed = ""
        self._forget_result()

    def _forget_result(self) -> None:
        """Drop the result kept for scrolling (``_memory_result``): the rows
        it came from are gone."""
        self._result: nw.DataFrame | None = None
        self._result_key: str | None = None

    @property
    def live_limit(self) -> int | None:
        """The most rows a query gives: ``max_memory_rows`` in live mode, as
        libraries that cannot skip rows read all rows before each page; None
        in memory mode, which holds no more."""
        return self.max_memory_rows if self.mode == "live" else None

    def mode_state(self) -> dict[str, Any]:
        """The mode for the frontend: {"mode", "fixed", "memory", "partial",
        "live_limit", "max_memory_rows"} (see ``_open``)."""
        return {
            "mode": self.mode,
            "fixed": self.fixed,
            "memory": self.memory,
            "partial": self.partial,
            "live_limit": self.live_limit,
            "max_memory_rows": self.max_memory_rows,
        }

    def switch_mode(self, content: dict[str, Any]) -> dict[str, Any]:
        """Switch to ``content["mode"]`` ("live" or "memory"): the new mode, the
        columns (reading into memory may change their types) and the
        frontend's settings fitted to them."""
        mode = content.get("mode")
        if mode not in ("live", "memory"):
            return {"error": f"unknown mode {mode!r}"}
        if self.fixed and mode != self.mode:
            return {"error": self.fixed}
        try:
            if mode == "memory" and self.mode != "memory":
                self._load_memory()
            elif mode == "live" and self.mode != "live":
                self._go_live()
        except Exception as exc:
            return {"error": error_text(exc), **self._view(content)}
        self.requested = mode
        view = self._view(content)
        self._remember(view["settings"])
        return view

    def _remembered(self) -> dict[str, Any] | None:
        """The settings remembered for the data, or None."""
        state = self.states.query(self.key)
        return state.settings.to_dict() if state is not None else None

    def _remember(self, settings: dict[str, Any]) -> None:
        """Remember ``settings`` and the mode asked for (not "auto"'s choice,
        which may differ when the data has grown or shrunk)."""
        self.states.remember_query(
            self.key, QuerySettings.from_dict(settings), self.requested
        )

    def _view(self, content: dict[str, Any]) -> dict[str, Any]:
        """The columns, the frontend's settings fitted to them, the mode and
        the page size."""
        return {
            "columns": columns_info(self.schema),
            "settings": normalize_settings(content.get("settings"), self.schema),
            "mode": self.mode_state(),
            "page_rows": self.page_rows,
        }

    # --- Requests ---

    def reload(self, content: dict[str, Any]) -> dict[str, Any]:
        """Read the data again, e.g. after it changed on storage, in the mode
        last chosen: its columns, the frontend's settings fitted to them
        (columns may have changed), and the mode."""
        try:
            self._open(self.requested)
        except Exception as exc:
            return {"error": error_text(exc)}
        return self._view(content)

    def result(self, *, all_columns: bool = False) -> Any:
        """The data with the remembered settings applied (filters, sort order,
        hidden columns left out, unless ``all_columns``), as a dataframe of
        the data's own library.

        Built on the data itself, not on rows held in memory: it covers all of
        it, and stays lazy if the data is (e.g. a polars LazyFrame or a Spark
        DataFrame); eager data (e.g. pandas) gives the result computed. Filters
        run in the data's library, as in memory mode (for lazy data, in the
        library it was collected into, which may differ in details such as
        regex syntax, e.g. PyArrow's for Spark's).
        """
        data = nw.from_native(self.native)
        schema = data.collect_schema()
        settings = normalize_settings(self._remembered(), schema)
        if all_columns:
            settings = {**settings, "hidden": []}
        return build_query(data, schema, settings).to_native()

    def result_settings(self) -> dict[str, Any]:
        """The remembered settings ``result`` depends on (filters, sort,
        hidden; not widths), to tell when it changes."""
        settings = normalize_settings(self._remembered(), self.schema)
        return {key: settings[key] for key in ("filters", "sort", "hidden")}

    def opening(self) -> dict[str, Any]:
        """What the frontend needs to show the data: its columns, remembered
        settings and the mode."""
        return self._view({"settings": self._remembered()})

    def _memory_result(self, settings: dict[str, Any]) -> nw.DataFrame:
        """The rows in memory with ``settings`` applied, computed once for
        each filters, sort and hidden columns: scrolling asks for many pages
        of one result, and sorting them all again for each page would make
        each scroll as slow as the first page (pandas sorts a million rows in
        a quarter of a second). It holds at most the rows in memory."""
        key = repr([settings[name] for name in ("filters", "sort", "hidden")])
        if self._result_key != key:
            self._result = build_query(self.lf, self.schema, settings).collect()
            self._result_key = key
        return self._result

    def rows(self, content: dict[str, Any]) -> dict[str, Any]:
        """Rows ``offset`` to ``offset + window`` of the data, with the frontend's
        settings applied; also remembers those settings.

        "limited": the result has more rows than the live mode gives (see
        ``live_limit``). "total": the number of rows in the result, in memory
        mode only (counting live data could mean reading all of it, e.g. a
        Spark job), else None.
        """
        settings = normalize_settings(content.get("settings"), self.schema)
        self._remember(settings)
        offset = max(0, int(content.get("offset", 0)))
        window = max(1, int(content.get("window", 1000)))
        limit = self.live_limit
        if limit is not None:
            offset = min(offset, limit)
            window = max(0, min(window, limit - offset))
        try:
            # One extra row tells whether there are more.
            total = None
            if self.mode == "memory":
                result = self._memory_result(settings)
                df = result[offset : offset + window + 1]
                total = len(result)
            else:
                query = build_query(self.lf, self.schema, settings)
                df = self._read(query, offset, window + 1)
        except Exception as exc:
            return {"error": error_text(exc), "settings": settings}
        beyond = len(df) > window
        limited = beyond and limit is not None and offset + window >= limit
        df = df.head(window)
        # pandas marks missing values with NaN, also in text columns: shown as
        # missing, as other libraries' nulls (a NaN of theirs is a value).
        nan_missing = df.implementation.is_pandas_like()
        return {
            "offset": offset,
            "columns": df.columns,
            "dtypes": [str(t) for t in df.schema.values()],
            "rows": [
                [None if nan_missing and _is_nan(v) else jsonable(v) for v in row]
                for row in df.rows()
            ],
            "more": beyond and not limited,
            "limited": limited,
            "total": total,
            "settings": settings,
        }

    def check(self, content: dict[str, Any]) -> dict[str, Any]:
        """Check one filter before the frontend applies it: {} if it can run,
        else {"error": message} (e.g. an invalid regular expression)."""
        column = content["column"]
        settings = normalize_settings(
            {"filters": {column: content["filter"]}}, self.schema
        )
        if column not in settings["filters"]:
            if (content["filter"] or {}).get("op") == "range":
                return {"error": "enter a minimum, a maximum or both"}
            return {"error": f"this filter is not available for {column!r}"}
        try:
            check_filter(
                column,
                self.schema[column],
                settings["filters"][column],
                self.lf.implementation,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {}

    def save(self, content: dict[str, Any]) -> dict[str, Any]:
        """Remember settings changed without fetching rows (e.g. column widths)."""
        settings = normalize_settings(content.get("settings"), self.schema)
        self._remember(settings)
        return {}

    def handle(self, content: dict[str, Any]) -> dict[str, Any] | None:
        """The reply to a request by its "type", or None if it is not a query
        request (one of ``REQUESTS``)."""
        kind = content.get("type")
        handler = {
            "query_rows": self.rows,
            "query_check": self.check,
            "query_save": self.save,
            "query_reload": self.reload,
            "query_mode": self.switch_mode,
        }.get(kind)
        if handler is None:
            return None
        started = time.monotonic()
        reply = handler(content)
        where = getattr(self.key, "url", self.key)
        took = time.monotonic() - started
        if reply and reply.get("error"):
            log.warning("Data browser %s on %s: %s", kind, where, reply["error"])
        elif kind == "query_save":
            log.debug("Data browser %s on %s in %.3f s", kind, where, took)
        else:
            log.info(
                "Data browser %s on %s (%s mode) in %.2f s",
                kind,
                where,
                getattr(self, "mode", "?"),
                took,
            )
        return reply
