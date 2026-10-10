"""The data browser's query: filters, sort order and hidden columns over a polars LazyFrame.

Settings are plain JSON-like dicts, shared with the frontend and remembered
per dataset by a ``QuerySettingsStore``::

    {
        "filters": {
            "price": {"op": "gt", "value": "10"},
            "name": {"op": "contains", "value": "tea", "case_sensitive": False},
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
from typing import Any

from jupyter_storage_explorer.formats.requirements import Polars

# Filter types ("op") by kind of column. Ops in _NO_VALUE take no value.
_OPS_BY_KIND = {
    "text": ["not_null", "null", "eq", "contains", "regex", "not_empty", "empty"],
    "numeric": ["not_null", "null", "eq", "gt", "lt", "ge", "le"],
    "temporal": ["not_null", "null", "eq", "gt", "lt", "ge", "le"],
    "boolean": ["not_null", "null", "eq"],
    "other": ["not_null", "null"],
}
_NO_VALUE = {"not_null", "null", "not_empty", "empty"}
# Text filters that can ignore case ("case_sensitive": False in the filter).
_CASE_OPS = {"eq", "contains", "regex"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "filters": {},
    "sort": None,
    "hidden": [],
    "widths": {},
}
# Column widths (px) kept within this range.
_MIN_WIDTH, _MAX_WIDTH = 40, 2000


def _polars() -> Any:
    """polars, imported only when the data browser is used (it is optional)."""
    return Polars().load()


def column_kind(dtype: Any) -> str:
    """Which filters a polars column type gets: "text", "numeric", "temporal", "boolean" or "other"."""
    pl = _polars()
    if dtype.is_numeric():
        return "numeric"
    if dtype.is_temporal() and dtype != pl.Duration:
        return "temporal"
    if dtype == pl.Boolean:
        return "boolean"
    if dtype in (pl.String, pl.Categorical) or isinstance(dtype, pl.Enum):
        return "text"
    return "other"


def value_input(dtype: Any, kind: str) -> str:
    """The field the filter dialog shows for a value: "text", "number", "date",
    "datetime", "time" or "boolean"."""
    pl = _polars()
    if kind == "numeric":
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "temporal":
        if dtype == pl.Date:
            return "date"
        return "time" if dtype == pl.Time else "datetime"
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
            op = f.get("op")
            kind = column_kind(schema[column])
            if op in _OPS_BY_KIND[kind]:
                filters[column] = {
                    "op": op,
                    "value": "" if op in _NO_VALUE else str(f.get("value", "")),
                }
                if kind == "text" and op in _CASE_OPS:
                    filters[column]["case_sensitive"] = bool(
                        f.get("case_sensitive", True)
                    )
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


def _parse_value(op: str, value: str, dtype: Any, kind: str) -> Any:
    """The filter value as a polars literal of the column's type."""
    pl = _polars()
    text = value.strip()
    if kind == "numeric":
        try:
            number: Any = int(text) if dtype.is_integer() else float(text)
        except ValueError:
            # e.g. "1.5" for an integer column; raises if not a number at all
            number = float(text)
        return pl.lit(number)
    if kind == "temporal":
        return _temporal_literal(text, dtype)
    if kind == "boolean":
        if text.lower() in ("true", "1", "yes"):
            return pl.lit(True)
        if text.lower() in ("false", "0", "no"):
            return pl.lit(False)
        raise ValueError(f"{value!r} is not true or false")
    return pl.lit(value)  # text: as typed, spaces included


def _temporal_literal(text: str, dtype: Any) -> Any:
    """ISO text (e.g. "2025-01-31", "2025-01-31 12:00") as a literal of a date,
    datetime or time column's type.

    Parsed with Python, as polars 2 no longer casts text to dates.
    """
    pl = _polars()
    if dtype == pl.Date:
        return pl.lit(dt.date.fromisoformat(text))
    if dtype == pl.Time:
        return pl.lit(dt.time.fromisoformat(text))
    value = dt.datetime.fromisoformat(text)  # a date alone means midnight
    literal = pl.lit(value).cast(pl.Datetime(dtype.time_unit))
    time_zone = getattr(dtype, "time_zone", None)
    if time_zone:
        # Text with an offset is converted; plain text is read in the column's zone.
        if value.tzinfo is not None:
            return pl.lit(value).dt.convert_time_zone(time_zone)
        return literal.dt.replace_time_zone(time_zone)
    return literal


def filter_expression(
    column: str, dtype: Any, op: str, value: str, case_sensitive: bool = True
) -> Any:
    """The polars expression keeping rows that match one column's filter.

    ``case_sensitive`` applies to text "eq", "contains" and "regex".
    """
    pl = _polars()
    col = pl.col(column)
    kind = column_kind(dtype)
    if kind == "text" and dtype != pl.String:
        col = col.cast(pl.String)  # categorical/enum values compared as text
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
        return col.str.contains(value if case_sensitive else f"(?i){value}")
    if kind == "text" and not case_sensitive:
        col, value = col.str.to_lowercase(), value.lower()
    if op == "contains":
        return col.str.contains(value, literal=True)
    literal = _parse_value(op, value, dtype, kind)
    comparisons = {
        "eq": col == literal,
        "gt": col > literal,
        "lt": col < literal,
        "ge": col >= literal,
        "le": col <= literal,
    }
    return comparisons[op]


def check_filter(column: str, dtype: Any, f: dict[str, Any]) -> None:
    """Raise ValueError with a readable message if a filter cannot run.

    Catches values that do not fit the column (e.g. "abc" for a number) and
    regular expressions polars cannot compile, before the filter is applied.
    """
    pl = _polars()
    case_sensitive = f.get("case_sensitive", True)
    try:
        filter_expression(column, dtype, f["op"], f["value"], case_sensitive)
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if f["op"] == "regex":
        pattern = f["value"] if case_sensitive else f"(?i){f['value']}"
        try:
            # polars compiles the pattern when the expression runs.
            pl.select(pl.lit("").str.contains(pattern))
        except Exception as exc:
            # Keep polars' explanation; drop its query-plan context.
            message = str(exc).split("\n\nThis error occurred")[0]
            raise ValueError(message.split("\n\nResolved plan")[0]) from exc


def build_query(lf: Any, schema: Any, settings: dict[str, Any]) -> Any:
    """``lf`` filtered, sorted and with hidden columns left out, per ``settings``.

    Raises ValueError for a filter value that does not fit its column.
    """
    for column, f in settings["filters"].items():
        try:
            lf = lf.filter(
                filter_expression(
                    column,
                    schema[column],
                    f["op"],
                    f["value"],
                    f.get("case_sensitive", True),
                )
            )
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
