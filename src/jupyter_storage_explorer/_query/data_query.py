"""One dataset open in the data browser (``DataQuery``): its modes, pages of
rows and requests; and ``fetch_rows``, how a page is read."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import narwhals as nw

from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query.filters import (
    build_query,
    check_filter,
    columns_info,
    normalize_settings,
)
from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer.formats.requirements import Polars

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer._explorer.states import ExplorerStates

MODES = ("auto", "live", "memory")


def _memory_backend() -> str | None:
    """The library data in memory is queried with: polars when it is installed,
    as it is faster and the same for all data; otherwise the data's own."""
    return "polars" if Polars().is_installed() else None


def as_lazy(frame: Any) -> nw.LazyFrame:
    """A dataframe of any library narwhals supports, as a narwhals LazyFrame.

    Eager dataframes (pandas, PyArrow, ...) are queried in memory (see
    ``_memory_backend``).
    """
    data = nw.from_native(frame)
    if isinstance(data, nw.DataFrame):
        return data.lazy(_memory_backend())
    return data


def fetch_rows(lf: nw.LazyFrame, offset: int, length: int) -> nw.DataFrame:
    """Read one page of a query's result, for the data browser's table.

    The default of ``DataExplorer``'s and ``StorageExplorer``'s
    ``fetch_rows``, which replace it for live queries only (rows in memory
    always use it), and fall back to it for pages they return None for.
    polars and DuckDB skip the rows before ``offset``
    themselves; other libraries (e.g. Spark) have no portable way to, so all
    rows up to ``offset + length`` are read and the first ones dropped.

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
    df = lf.head(offset + length).collect()
    return df.tail(max(0, len(df) - offset))


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
      with polars when installed (see ``_memory_backend``).

    ``mode`` chooses the mode to start in. "auto" (the default) is "live" for
    lazy data, unless it has at most ``max_live_rows`` rows: the first query
    reads them all anyway, so they are kept in memory. Eager data (pandas,
    PyArrow, polars DataFrames, ...) is always queried in memory, so "live"
    raises ValueError for it. When all the data is in memory, the mode cannot
    be switched.
    """

    def __init__(
        self,
        source: Any,
        key: str,
        states: ExplorerStates,
        *,
        mode: str = "auto",
        max_live_rows: int = 5000,
        max_memory_rows: int = 100_000,
        fetch: Callable[[nw.LazyFrame, int, int], nw.DataFrame | None] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        self.scan: Callable[[], Any] = source if callable(source) else lambda: source
        self.key = key
        self.states = states
        self.max_live_rows = max_live_rows
        self.max_memory_rows = max_memory_rows
        self.fetch = fetch
        # The mode asked for, by the caller or the user: reloading starts in it.
        self.requested = mode
        self._open(mode)

    # --- Modes ---

    def _open(self, mode: str) -> None:
        """Read the data (again) and set up queries in ``mode`` ("auto", "live" or "memory").

        Sets ``implementation`` (the data's library), ``source`` (the lazy
        data, or None for eager data), ``mode``,
        ``lf`` (what queries run on), ``schema``, ``memory`` ({"rows",
        "cut"}: rows held and whether there are more, or None in live mode)
        and ``fixed`` (why the mode cannot be switched, or "").
        """
        native = self.scan()
        data = nw.from_native(native)
        # The data as given (or as the function returned it), for ``result``.
        self.native = native
        # The data's own library (queries in memory may run in polars instead)
        # and type, e.g. "LazyFrame".
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
            self._hold(data, cut=False)
            self.fixed = "The data is a dataframe in memory."
            return
        self.source = data
        if mode == "memory":
            self._load_memory()
        elif not self._fits_live_rows():
            self._go_live()

    def _fits_live_rows(self) -> bool:
        """Keep the data in memory if it has at most ``max_live_rows`` rows."""
        head = self.source.head(self.max_live_rows + 1).collect(_memory_backend())
        if len(head) > self.max_live_rows:
            return False
        self._hold(head, cut=False)
        # Live queries would read the same rows again: nothing to switch to.
        self.fixed = f"All {len(head):,} rows are in memory."
        return True

    def _load_memory(self) -> None:
        """Read the first ``max_memory_rows`` rows into memory, to query them there."""
        rows = self.source.head(self.max_memory_rows + 1).collect(_memory_backend())
        cut = len(rows) > self.max_memory_rows
        self._hold(rows.head(self.max_memory_rows), cut=cut)

    def _hold(self, df: nw.DataFrame, *, cut: bool) -> None:
        """Query ``df`` in memory; ``cut``: the data has more rows."""
        self.mode = "memory"
        self.lf = df.lazy(_memory_backend())
        self.schema = self.lf.collect_schema()
        self.memory = {"rows": len(df), "cut": cut}
        self.fixed = ""

    def _go_live(self) -> None:
        self.mode = "live"
        self.lf = self.source
        self.schema = self.lf.collect_schema()
        self.memory = None
        self.fixed = ""

    @property
    def live_limit(self) -> int | None:
        """The most rows a query gives: ``max_memory_rows`` in live mode, as
        libraries that cannot skip rows read all rows before each page; None
        in memory mode, which holds no more."""
        return self.max_memory_rows if self.mode == "live" else None

    def mode_state(self) -> dict[str, Any]:
        """The mode for the frontend: {"mode", "fixed", "memory", "live_limit",
        "max_memory_rows"} (see ``_open``)."""
        return {
            "mode": self.mode,
            "fixed": self.fixed,
            "memory": self.memory,
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
            return {"error": f"{type(exc).__name__}: {exc}", **self._view(content)}
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
        """The columns, the frontend's settings fitted to them, and the mode."""
        return {
            "columns": columns_info(self.schema),
            "settings": normalize_settings(content.get("settings"), self.schema),
            "mode": self.mode_state(),
        }

    # --- Requests ---

    def reload(self, content: dict[str, Any]) -> dict[str, Any]:
        """Read the data again, e.g. after it changed on storage, in the mode
        last chosen: its columns, the frontend's settings fitted to them
        (columns may have changed), and the mode."""
        try:
            self._open(self.requested)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        return self._view(content)

    def result(self, *, all_columns: bool = False) -> Any:
        """The data with the remembered settings applied (filters, sort order,
        hidden columns left out, unless ``all_columns``), as a dataframe of
        the data's own library.

        Built on the data itself, not on rows held in memory: it covers all of
        it, and stays lazy if the data is (e.g. a polars LazyFrame or a Spark
        DataFrame); eager data (e.g. pandas) gives the result computed. Filters
        run in the data's library, so their details (e.g. regex syntax) may
        differ from what the data browser showed in memory mode, which uses
        polars.
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
            query = build_query(self.lf, self.schema, settings)
            # ``fetch`` is for the data's library: rows in memory may be in
            # polars. It returns None to leave a page to the default.
            df = None
            if self.mode == "live" and self.fetch is not None:
                df = self.fetch(query, offset, window + 1)
            if df is None:
                df = fetch_rows(query, offset, window + 1)
            total = None
            if self.mode == "memory":
                total = query.select(nw.len()).collect().item()
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "settings": settings}
        beyond = len(df) > window
        limited = beyond and limit is not None and offset + window >= limit
        df = df.head(window)
        return {
            "offset": offset,
            "columns": df.columns,
            "dtypes": [str(t) for t in df.schema.values()],
            "rows": [[jsonable(v) for v in row] for row in df.rows()],
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
        """The reply to a request by its "type", or None if it is not a query request."""
        handler = {
            "query_rows": self.rows,
            "query_check": self.check,
            "query_save": self.save,
            "query_reload": self.reload,
            "query_mode": self.switch_mode,
        }.get(content.get("type"))
        return handler(content) if handler is not None else None
