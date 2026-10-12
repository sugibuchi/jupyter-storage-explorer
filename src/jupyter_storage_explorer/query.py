"""The data browser's query: filters, sort order and hidden columns over a dataframe.

The data can be any dataframe narwhals supports, lazy (polars LazyFrame,
DuckDB, Spark, ...) or eager (pandas, polars, PyArrow, ...); queries are
narwhals expressions, run by the data's own library. So some details follow
that library, e.g. the syntax of regular expressions.

Settings are plain JSON-like dicts, shared with the frontend and remembered
per dataset by a ``QuerySettingsStore``::

    {
        "filters": {
            "price": {"op": "range", "min": "10", "max": ""},  # price >= 10
            "name": {"op": "contains", "value": "tea", "case_sensitive": False},
            "comment": {"op": "not_null"},
        },
        "sort": {"column": "date", "descending": True},  # or None
        "hidden": ["comment"],
        "widths": {"name": 180},  # px; empty: automatic widths
    }
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
from typing import TYPE_CHECKING, Any

import narwhals as nw

from jupyter_storage_explorer.formats.base import jsonable
from jupyter_storage_explorer.formats.requirements import Polars

if TYPE_CHECKING:
    from collections.abc import Callable

# Filter types ("op") by kind of column. Ops in _NO_VALUE take no value;
# "range" takes "min" and "max" (inclusive; either may be empty); the others
# take a "value".
_OPS_BY_KIND = {
    "text": ["not_null", "null", "not_empty", "empty", "contains", "regex", "range"],
    "numeric": ["not_null", "null", "range"],
    "temporal": ["not_null", "null", "range"],
    "boolean": ["not_null", "null", "eq"],
    "other": ["not_null", "null"],
}
_NO_VALUE = {"not_null", "null", "not_empty", "empty"}
# Text filters that can ignore case ("case_sensitive": False in the filter).
_CASE_OPS = {"contains", "regex", "range"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "filters": {},
    "sort": None,
    "hidden": [],
    "widths": {},
}
# Column widths (px) kept within this range.
_MIN_WIDTH, _MAX_WIDTH = 40, 2000


def column_kind(dtype: Any) -> str:
    """Which filters a (narwhals) column type gets: "text", "numeric", "temporal", "boolean" or "other"."""
    if dtype.is_numeric():
        return "numeric"
    if dtype.is_temporal() and dtype != nw.Duration:
        return "temporal"
    if dtype == nw.Boolean:
        return "boolean"
    if dtype in (nw.String, nw.Categorical, nw.Enum):
        return "text"
    return "other"


def value_input(dtype: Any, kind: str) -> str:
    """The field the filter dialog shows for a value: "text", "number", "date",
    "datetime", "time" or "boolean"."""
    if kind == "numeric":
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "temporal":
        if dtype == nw.Date:
            return "date"
        return "time" if dtype == nw.Time else "datetime"
    return "text"


def columns_info(schema: Any) -> list[dict[str, Any]]:
    """Name, type, kind, value field and allowed filter types of each column, for the frontend."""
    columns = []
    for name, dtype in schema.items():
        kind = column_kind(dtype)
        columns.append(
            {
                "name": name,
                "dtype": str(dtype),
                "kind": kind,
                "input": value_input(dtype, kind),
                "ops": _OPS_BY_KIND[kind],
            }
        )
    return columns


def normalize_settings(settings: Any, schema: Any) -> dict[str, Any]:
    """Valid settings for ``schema``: unknown columns and malformed parts are dropped.

    Remembered settings may refer to columns the data no longer has.
    """
    settings = settings if isinstance(settings, dict) else {}
    filters = {}
    for column, f in (settings.get("filters") or {}).items():
        if column in schema and isinstance(f, dict):
            kind = column_kind(schema[column])
            normalized = _normalize_filter(f, kind)
            if normalized is not None:
                filters[column] = normalized
    sort = settings.get("sort")
    if not (isinstance(sort, dict) and sort.get("column") in schema):
        sort = None
    else:
        sort = {"column": sort["column"], "descending": bool(sort.get("descending"))}
    hidden = [c for c in settings.get("hidden") or [] if c in schema]
    widths = {
        c: int(min(_MAX_WIDTH, max(_MIN_WIDTH, w)))
        for c, w in (settings.get("widths") or {}).items()
        if c in schema and isinstance(w, (int, float)) and not isinstance(w, bool)
    }
    return {"filters": filters, "sort": sort, "hidden": hidden, "widths": widths}


def _normalize_filter(f: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """A filter in its canonical form, or None if it does not apply to the column."""
    op = f.get("op")
    if op not in _OPS_BY_KIND[kind]:
        return None  # e.g. a filter type of an earlier version
    if op in _NO_VALUE:
        return {"op": op}
    if op == "range":
        bounds = {b: str(f.get(b) or "") for b in ("min", "max")}
        if not any(v.strip() for v in bounds.values()):
            return None  # no bound: nothing to filter
        normalized: dict[str, Any] = {"op": op, **bounds}
    else:
        normalized = {"op": op, "value": str(f.get("value", ""))}
    if kind == "text" and op in _CASE_OPS:
        normalized["case_sensitive"] = bool(f.get("case_sensitive", True))
    return normalized


def _parse_value(value: str, dtype: Any, kind: str) -> Any:
    """The filter value as a literal of the column's type."""
    text = value.strip()
    if kind == "numeric":
        try:
            number: Any = int(text) if dtype.is_integer() else float(text)
        except ValueError:
            # e.g. "1.5" for an integer column; raises if not a number at all
            number = float(text)
        return nw.lit(number)
    if kind == "temporal":
        return _temporal_literal(text, dtype)
    if kind == "boolean":
        if text.lower() in ("true", "1", "yes"):
            return nw.lit(True)
        if text.lower() in ("false", "0", "no"):
            return nw.lit(False)
        raise ValueError(f"{value!r} is not true or false")
    return nw.lit(value)  # text: as typed, spaces included


def _temporal_literal(text: str, dtype: Any) -> Any:
    """ISO text (e.g. "2025-01-31", "2025-01-31 12:00") as a literal of a date,
    datetime or time column's type.

    Parsed with Python, as libraries differ in casting text to dates (polars 2
    no longer does).
    """
    if dtype == nw.Date:
        return nw.lit(dt.date.fromisoformat(text), nw.Date)
    if dtype == nw.Time:
        return nw.lit(dt.time.fromisoformat(text), nw.Time)
    value = dt.datetime.fromisoformat(text)  # a date alone means midnight
    time_unit = getattr(dtype, "time_unit", "us")
    time_zone = getattr(dtype, "time_zone", None)
    if time_zone:
        # Text with an offset is converted; plain text is read in the column's zone.
        if value.tzinfo is not None:
            return nw.lit(value).dt.convert_time_zone(time_zone)
        return nw.lit(value, nw.Datetime(time_unit)).dt.replace_time_zone(time_zone)
    return nw.lit(value, nw.Datetime(time_unit))


def filter_expression(column: str, dtype: Any, f: dict[str, Any]) -> Any:
    """The expression keeping rows that match one column's filter ``f`` (as
    normalized by ``normalize_settings``).

    "range" keeps values between "min" and "max", both included; an empty
    bound is open. ``f["case_sensitive"]`` (default True) applies to text
    "contains", "regex" and "range".
    """
    col = nw.col(column)
    kind = column_kind(dtype)
    op = f["op"]
    case_sensitive = f.get("case_sensitive", True)
    if kind == "text" and dtype != nw.String:
        col = col.cast(nw.String)  # categorical/enum values compared as text
    if op == "null":
        return col.is_null()
    if op == "not_null":
        return col.is_not_null()
    if op == "empty":
        return col == ""
    if op == "not_empty":
        return col.is_not_null() & (col != "")
    if op == "regex":
        # (?i) makes the whole pattern ignore case.
        value = f["value"]
        return col.str.contains(value if case_sensitive else f"(?i){value}")
    ignore_case = kind == "text" and not case_sensitive
    if ignore_case:
        col = col.str.to_lowercase()
    if op == "contains":
        value = f["value"].lower() if ignore_case else f["value"]
        return col.str.contains(value, literal=True)
    if op == "range":
        return _range_expression(col, dtype, kind, f, ignore_case)
    return col == _parse_value(f["value"], dtype, kind)  # "eq" (booleans)


def _range_expression(
    col: Any, dtype: Any, kind: str, f: dict[str, Any], ignore_case: bool
) -> Any:
    """``col`` between ``f["min"]`` and ``f["max"]``, both included; an empty bound is open.

    With ``ignore_case``, ``col`` is already lower case, and the bounds are made so.
    """
    conditions = []
    for bound, name in (("min", "minimum"), ("max", "maximum")):
        text = f[bound]
        if kind != "text":
            text = text.strip()  # "10 " is 10; text keeps its spaces
        if not text:
            continue
        try:
            literal = _parse_value(text.lower() if ignore_case else text, dtype, kind)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
        conditions.append(col >= literal if bound == "min" else col <= literal)
    if not conditions:
        raise ValueError("enter a minimum, a maximum or both")
    return conditions[0] if len(conditions) == 1 else conditions[0] & conditions[1]


def check_filter(
    column: str,
    dtype: Any,
    f: dict[str, Any],
    implementation: nw.Implementation = nw.Implementation.POLARS,
) -> None:
    """Raise ValueError with a readable message if a filter cannot run.

    Catches values that do not fit the column (e.g. "abc" for a number) and
    regular expressions the data's library (``implementation``) cannot
    compile, before the filter is applied. Libraries that need more than a
    one-row table to try a pattern on (e.g. Spark, which needs a session)
    report bad patterns only when the rows are read.
    """
    case_sensitive = f.get("case_sensitive", True)
    try:
        filter_expression(column, dtype, f)
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if f["op"] == "regex":
        pattern = f["value"] if case_sensitive else f"(?i){f['value']}"
        try:
            probe = nw.from_dict({"v": [""]}, backend=implementation)
        except Exception:
            return
        try:
            # Libraries compile the pattern when the expression runs.
            probe.select(nw.col("v").str.contains(pattern))
        except Exception as exc:
            # Keep the library's explanation; drop polars' query-plan context.
            message = str(exc).split("\n\nThis error occurred")[0]
            raise ValueError(message.split("\n\nResolved plan")[0]) from exc


def build_query(lf: nw.LazyFrame, schema: Any, settings: dict[str, Any]) -> Any:
    """``lf`` filtered, sorted and with hidden columns left out, per ``settings``.

    Raises ValueError for a filter value that does not fit its column.
    """
    for column, f in settings["filters"].items():
        try:
            lf = lf.filter(filter_expression(column, schema[column], f))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"filter on {column!r}: {exc}") from exc
    if settings["sort"]:
        lf = lf.sort(
            settings["sort"]["column"],
            descending=settings["sort"]["descending"],
            nulls_last=True,
        )
    visible = [c for c in schema if c not in settings["hidden"]]
    return lf.select(visible)


class QuerySettingsStore:
    """Remembers the data browser's settings per dataset (keyed by its location).

    By default only while the kernel runs; with ``path``, also in that JSON
    file, so they survive restarts.
    """

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        self.path = pathlib.Path(path) if path is not None else None
        self._settings: dict[str, dict[str, Any]] = {}
        if self.path is not None and self.path.exists():
            self._settings = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str) -> dict[str, Any] | None:
        settings = self._settings.get(key)
        return copy.deepcopy(settings) if settings is not None else None

    def set(self, key: str, settings: dict[str, Any]) -> None:
        if settings == DEFAULT_SETTINGS:
            self._settings.pop(key, None)  # nothing worth remembering
        else:
            self._settings[key] = copy.deepcopy(settings)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")


# Shared by all explorers in the kernel, so reopening data in a new explorer
# restores its settings too.
default_store = QuerySettingsStore()


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


def has_offsets(lf: nw.LazyFrame) -> bool:
    """Whether ``lf``'s library can skip rows itself (see ``fetch_rows``)."""
    return lf.implementation.is_polars() or lf.implementation.is_duckdb()


def fetch_rows(lf: nw.LazyFrame, offset: int, length: int) -> nw.DataFrame:
    """Rows ``offset`` to ``offset + length`` of ``lf``, read.

    polars and DuckDB skip the rows before ``offset`` themselves; other
    libraries (e.g. Spark) have no portable way to, so all rows up to
    ``offset + length`` are read and the first ones dropped here.
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
    to read a file again). Settings are remembered in ``store`` under ``key``
    (e.g. the data's URL). The frontend's requests are "query_rows",
    "query_check", "query_save", "query_reload" and "query_mode" (see
    static/query.js).

    Queries run in one of two modes, switched between in the data browser:

    - "live": on the source itself, e.g. a polars LazyFrame or a Spark
      DataFrame, each query reading the data again. Libraries that cannot
      skip rows (see ``has_offsets``, e.g. Spark) give only the first
      ``max_live_rows`` rows of each result.
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
        store: QuerySettingsStore,
        *,
        mode: str = "auto",
        max_live_rows: int = 1000,
        max_memory_rows: int = 100_000,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        self.scan: Callable[[], Any] = source if callable(source) else lambda: source
        self.key = key
        self.store = store
        self.max_live_rows = max_live_rows
        self.max_memory_rows = max_memory_rows
        # The mode asked for, by the caller or the user: reloading starts in it.
        self.requested = mode
        self._open(mode)

    # --- Modes ---

    def _open(self, mode: str) -> None:
        """Read the data (again) and set up queries in ``mode`` ("auto", "live" or "memory").

        Sets ``source`` (the lazy data, or None for eager data), ``mode``,
        ``lf`` (what queries run on), ``schema``, ``memory`` ({"rows",
        "cut"}: rows held and whether there are more, or None in live mode)
        and ``fixed`` (why the mode cannot be switched, or "").
        """
        data = nw.from_native(self.scan())
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
        """The most rows a query gives (live mode without offsets), or None for no limit."""
        if self.mode == "live" and not has_offsets(self.lf):
            return self.max_live_rows
        return None

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
        return self._view(content)

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

    def opening(self) -> dict[str, Any]:
        """What the frontend needs to show the data: its columns, remembered
        settings and the mode."""
        return self._view({"settings": self.store.get(self.key)})

    def rows(self, content: dict[str, Any]) -> dict[str, Any]:
        """Rows ``offset`` to ``offset + window`` of the data, with the frontend's
        settings applied; also remembers those settings.

        "limited": the result has more rows than the live mode gives (see
        ``live_limit``). "total": the number of rows in the result, in memory
        mode only (counting live data could mean reading all of it, e.g. a
        Spark job), else None.
        """
        settings = normalize_settings(content.get("settings"), self.schema)
        self.store.set(self.key, settings)
        offset = max(0, int(content.get("offset", 0)))
        window = max(1, int(content.get("window", 1000)))
        limit = self.live_limit
        if limit is not None:
            offset = min(offset, limit)
            window = max(0, min(window, limit - offset))
        try:
            # One extra row tells whether there are more.
            query = build_query(self.lf, self.schema, settings)
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
        self.store.set(self.key, settings)
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
