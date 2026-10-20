"""The data browser's filters, sort and columns: settings checked against a
dataframe's schema, and the narwhals expressions applying them."""

from __future__ import annotations

import datetime as dt
from typing import Any

import narwhals as nw

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
        # Bounds may be given as numbers or dates (from Python, see QuerySettings).
        bounds = {b: as_text(f.get(b)) for b in ("min", "max")}
        if not any(v.strip() for v in bounds.values()):
            return None  # no bound: nothing to filter
        normalized: dict[str, Any] = {"op": op, **bounds}
    else:
        normalized = {"op": op, "value": as_text(f.get("value"))}
    if kind == "text" and op in _CASE_OPS:
        normalized["case_sensitive"] = bool(f.get("case_sensitive", True))
    return normalized


def as_text(value: Any) -> str:
    """A filter value as the frontend's text: "" for none, ISO for dates,
    "true"/"false" for booleans."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    return str(value)


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
