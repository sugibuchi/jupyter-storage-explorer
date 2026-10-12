"""query.py: the data browser's settings, filters, paging and remembered settings."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import duckdb
import narwhals as nw
import polars as pl
import pytest

from jupyter_storage_explorer import query as query_module
from jupyter_storage_explorer.formats.base import jsonable
from jupyter_storage_explorer.query import (
    DEFAULT_SETTINGS,
    DataQuery,
    QuerySettingsStore,
    build_query,
    check_filter,
    columns_info,
    normalize_settings,
)

DF = pl.DataFrame(
    {
        "name": ["Tea", "coffee", "Water", None],
        "price": [3, 5, 1, 2],
        "day": [dt.date(2025, 1, d) for d in (1, 2, 3, 4)],
        "ok": [True, False, True, None],
    }
)
SCHEMA = nw.from_native(DF).schema

# The libraries queries run in, each with the data as its own dataframe.
NATIVE = {
    "polars": DF.lazy,
    # Arrow-backed types, as pandas reads files with: booleans with missing
    # values keep their type (with NumPy types they are objects, see below).
    "pandas": lambda: DF.to_pandas(use_pyarrow_extension_array=True),
    "pyarrow": DF.to_arrow,
    "duckdb": lambda: duckdb.from_arrow(DF.to_arrow()),
}


@pytest.fixture(params=list(NATIVE))
def lf(request) -> nw.LazyFrame:
    """The data as a LazyFrame of each library (not converted to polars)."""
    return nw.from_native(NATIVE[request.param]()).lazy()


def values(df: Any, column: str) -> list[Any]:
    """A column's values, with missing values (None or NaN, per library) as None."""
    return [
        None if jsonable(v) is None or (isinstance(v, float) and math.isnan(v)) else v
        for v in df.get_column(column).to_list()
    ]


def run(settings: dict, lf: nw.LazyFrame | None = None) -> nw.DataFrame:
    lf = lf if lf is not None else nw.from_native(DF.lazy())
    schema = lf.collect_schema()
    return build_query(lf, schema, normalize_settings(settings, schema)).collect()


def test_columns_info():
    info = {c["name"]: c for c in columns_info(SCHEMA)}
    assert (info["name"]["kind"], info["name"]["input"]) == ("text", "text")
    assert (info["price"]["kind"], info["price"]["input"]) == ("numeric", "number")
    assert (info["day"]["kind"], info["day"]["input"]) == ("temporal", "date")
    assert info["ok"]["ops"] == ["not_null", "null", "eq"]


class TestNormalizeSettings:
    def test_garbage(self):
        assert normalize_settings("nonsense", SCHEMA) == DEFAULT_SETTINGS

    def test_drops_unknown_columns_and_ops(self):
        settings = normalize_settings(
            {
                "filters": {
                    "gone": {"op": "null"},
                    "price": {"op": "contains", "value": "1"},  # not a numeric filter
                    "name": {"op": "contains", "value": "t"},
                },
                "sort": {"column": "gone"},
                "hidden": ["gone", "ok"],
                "widths": {"name": 5, "price": 99999, "day": "wide", "ok": True},
            },
            SCHEMA,
        )
        assert settings == {
            "filters": {
                "name": {"op": "contains", "value": "t", "case_sensitive": True}
            },
            "sort": None,
            "hidden": ["ok"],
            "widths": {"name": 40, "price": 2000},
        }

    def test_empty_range_dropped(self):
        settings = normalize_settings(
            {"filters": {"price": {"op": "range", "min": " ", "max": ""}}}, SCHEMA
        )
        assert settings["filters"] == {}


class TestFilters:
    """Each filter, run by each library."""

    def test_contains_ignoring_case(self, lf):
        f = {"op": "contains", "value": "TE", "case_sensitive": False}
        df = run({"filters": {"name": f}}, lf)
        assert values(df, "name") == ["Tea", "Water"]

    def test_regex(self, lf):
        df = run({"filters": {"name": {"op": "regex", "value": "^[A-Z]"}}}, lf)
        assert values(df, "name") == ["Tea", "Water"]

    def test_regex_ignoring_case(self, lf):
        f = {"op": "regex", "value": "^w", "case_sensitive": False}
        assert values(run({"filters": {"name": f}}, lf), "name") == ["Water"]

    def test_numeric_range_open_end(self, lf):
        df = run({"filters": {"price": {"op": "range", "min": "2", "max": ""}}}, lf)
        assert values(df, "price") == [3, 5, 2]

    def test_date_range(self, lf):
        f = {"op": "range", "min": "2025-01-02", "max": "2025-01-03"}
        assert values(run({"filters": {"day": f}}, lf), "price") == [5, 1]

    def test_null(self, lf):
        assert values(run({"filters": {"name": {"op": "null"}}}, lf), "price") == [2]

    def test_boolean(self, lf):
        df = run({"filters": {"ok": {"op": "eq", "value": "yes"}}}, lf)
        assert values(df, "price") == [3, 1]

    def test_sort_nulls_last_and_hidden(self, lf):
        settings = {
            "sort": {"column": "name", "descending": True},
            "hidden": ["day", "ok"],
        }
        df = run(settings, lf)
        assert df.columns == ["name", "price"]
        assert values(df, "name") == ["coffee", "Water", "Tea", None]

    def test_datetime_with_time_zone(self):
        df = pl.DataFrame(
            {
                "at": [
                    dt.datetime(2025, 1, 1, 9, tzinfo=dt.UTC),
                    dt.datetime(2025, 1, 1, 12, tzinfo=dt.UTC),
                ]
            }
        ).with_columns(pl.col("at").dt.convert_time_zone("Europe/Paris"))
        lf = nw.from_native(df.lazy())
        # Plain text is read in the column's zone: 11:00 in Paris is 10:00 UTC.
        f = {"op": "range", "min": "2025-01-01 11:00", "max": ""}
        assert len(run({"filters": {"at": f}}, lf)) == 1
        f = {"op": "range", "min": "2025-01-01T09:30+00:00", "max": ""}
        assert len(run({"filters": {"at": f}}, lf)) == 1

    @pytest.mark.parametrize(
        ("column", "f", "message"),
        [
            ("price", {"op": "range", "min": "abc", "max": ""}, "minimum"),
            ("day", {"op": "range", "min": "", "max": "not a date"}, "maximum"),
            ("ok", {"op": "eq", "value": "maybe"}, "not true or false"),
            ("name", {"op": "regex", "value": "("}, "(?i)regex"),
        ],
    )
    def test_check_filter_errors(self, column, f, message):
        with pytest.raises(ValueError, match=message):
            check_filter(column, SCHEMA[column], f)

    def test_object_columns_only_get_null_filters(self):
        # pandas with NumPy types: booleans with a missing value are objects.
        schema = nw.from_native(DF.to_pandas()).schema
        info = {c["name"]: c for c in columns_info(schema)}
        assert info["ok"]["kind"] == "other"
        assert info["ok"]["ops"] == ["not_null", "null"]

    @pytest.mark.parametrize(
        ("implementation", "pattern", "message"),
        [
            # polars' regex has no look-around (pandas falls back to Python's re).
            (nw.Implementation.POLARS, "a(?=b)", "look-around"),
            (nw.Implementation.PANDAS, "(", "missing \\)"),
        ],
    )
    def test_regex_checked_by_the_datas_library(self, implementation, pattern, message):
        f = {"op": "regex", "value": pattern}
        with pytest.raises(ValueError, match=message):
            check_filter("name", SCHEMA["name"], f, implementation)

    def test_regex_not_checked_without_a_probe(self):
        # DuckDB cannot make a table from Python values here: the pattern is
        # only reported when rows are read.
        f = {"op": "regex", "value": "("}
        check_filter("name", SCHEMA["name"], f, nw.Implementation.DUCKDB)


class TestDataQuery:
    def query(self, store=None) -> DataQuery:
        return DataQuery(DF.lazy, "memory://data", store or QuerySettingsStore())

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(DF.lazy, id="polars-lazy"),
            pytest.param(DF, id="polars"),
            pytest.param(DF.to_pandas(), id="pandas"),
            pytest.param(lambda: duckdb.from_arrow(DF.to_arrow()), id="duckdb"),
        ],
    )
    def test_paging(self, source):
        query = DataQuery(source, "k", QuerySettingsStore())
        reply = query.handle({"type": "query_rows", "offset": 1, "window": 2})
        assert [row[:2] for row in reply["rows"]] == [["coffee", 5], ["Water", 1]]
        assert reply["more"] is True
        last = query.handle({"type": "query_rows", "offset": 2, "window": 2})
        assert [row[:2] for row in last["rows"]] == [["Water", 1], [None, 2]]
        assert last["more"] is False

    def test_paging_without_offsets(self, monkeypatch):
        # pandas, without polars to query it with: rows are read up to the
        # window's end and the first ones dropped.
        monkeypatch.setattr(query_module.Polars, "is_installed", lambda self: False)
        query = DataQuery(DF.to_pandas(), "k", QuerySettingsStore())
        assert query.lf.implementation.is_pandas()
        reply = query.handle({"type": "query_rows", "offset": 1, "window": 2})
        assert [row[0] for row in reply["rows"]] == ["coffee", "Water"]
        assert reply["more"] is True

    def test_missing_values_from_pandas(self, monkeypatch):
        monkeypatch.setattr(query_module.Polars, "is_installed", lambda self: False)
        data = DF.to_pandas(use_pyarrow_extension_array=True)
        query = DataQuery(data, "k", QuerySettingsStore())
        reply = query.handle({"type": "query_rows", "offset": 3, "window": 1})
        assert reply["rows"] == [[None, 2, "2025-01-04", None]]

    def test_eager_data_queried_with_polars(self):
        query = DataQuery(DF.to_pandas(), "k", QuerySettingsStore())
        assert query.lf.implementation.is_polars()

    def test_rows_as_json(self):
        reply = self.query().handle({"type": "query_rows", "offset": 0, "window": 1})
        assert reply["rows"] == [["Tea", 3, "2025-01-01", True]]
        assert reply["dtypes"] == ["String", "Int64", "Date", "Boolean"]

    def test_bad_filter_value(self):
        settings = {"filters": {"price": {"op": "range", "min": "abc", "max": ""}}}
        reply = self.query().rows({"settings": settings})
        assert "filter on 'price'" in reply["error"]

    def test_check(self):
        query = self.query()
        assert (
            query.check(
                {"column": "price", "filter": {"op": "range", "min": "1", "max": ""}}
            )
            == {}
        )
        assert query.check({"column": "price", "filter": {"op": "range"}}) == {
            "error": "enter a minimum, a maximum or both"
        }
        assert (
            "not available"
            in query.check(
                {"column": "price", "filter": {"op": "regex", "value": "x"}}
            )["error"]
        )

    def test_settings_remembered(self):
        store = QuerySettingsStore()
        settings = {"sort": {"column": "price", "descending": False}}
        self.query(store).rows({"settings": settings})
        assert self.query(store).opening()["settings"]["sort"] == {
            "column": "price",
            "descending": False,
        }

    def test_reload_fits_settings_to_new_columns(self):
        frames = iter([DF.lazy(), DF.drop("price").lazy()])
        query = DataQuery(lambda: next(frames), "k", QuerySettingsStore())
        reply = query.handle(
            {"type": "query_reload", "settings": {"hidden": ["price", "ok"]}}
        )
        assert [c["name"] for c in reply["columns"]] == ["name", "day", "ok"]
        assert reply["settings"]["hidden"] == ["ok"]

    def test_not_a_query_request(self):
        assert self.query().handle({"type": "preview"}) is None


class TestQuerySettingsStore:
    def test_persisted_in_file(self, tmp_path):
        path = tmp_path / "sub" / "settings.json"
        settings = {**DEFAULT_SETTINGS, "hidden": ["a"]}
        QuerySettingsStore(path).set("k", settings)
        assert QuerySettingsStore(path).get("k") == settings

    def test_defaults_forgotten(self):
        store = QuerySettingsStore()
        store.set("k", {**DEFAULT_SETTINGS, "hidden": ["a"]})
        store.set("k", DEFAULT_SETTINGS)
        assert store.get("k") is None

    def test_returns_copies(self):
        store = QuerySettingsStore()
        store.set("k", {**DEFAULT_SETTINGS, "hidden": ["a"]})
        store.get("k")["hidden"].append("b")
        assert store.get("k")["hidden"] == ["a"]
