"""_query/: the data browser's settings, filters, paging and remembered settings."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import duckdb
import narwhals as nw
import pandas as pd
import polars as pl
import pytest
from sqlframe.duckdb import DuckDBSession

from jupyter_storage_explorer._explorer.previews import _layered_fetch
from jupyter_storage_explorer._explorer.states import ExplorerStates
from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer._query import data_query
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.filters import (
    build_query,
    check_filter,
    columns_info,
    normalize_settings,
)
from jupyter_storage_explorer._query.settings import DEFAULT_SETTINGS

DF = pl.DataFrame(
    {
        "name": ["Tea", "coffee", "Water", None],
        "price": [3, 5, 1, 2],
        "day": [dt.date(2025, 1, d) for d in (1, 2, 3, 4)],
        "ok": [True, False, True, None],
    }
)
SCHEMA = nw.from_native(DF).schema


def spark_like(df: pl.DataFrame) -> Any:
    """``df`` as a PySpark-style DataFrame (sqlframe, on DuckDB), which narwhals
    queries as it does Spark: in SQL, without skipping rows (see fetch_rows).
    Stands in for Spark, which needs Java."""
    spark_types = {
        pl.Int64: "bigint",
        pl.String: "string",
        pl.Date: "date",
        pl.Boolean: "boolean",
    }
    schema = ", ".join(
        f"{name} {spark_types[dtype]}" for name, dtype in df.schema.items()
    )
    return DuckDBSession().createDataFrame(df.rows(), schema=schema)


# The libraries queries run in, each with the data as its own dataframe.
NATIVE = {
    "polars": DF.lazy,
    # Arrow-backed types, as pandas reads files with: booleans with missing
    # values keep their type (with NumPy types they are objects, see below).
    "pandas": lambda: DF.to_pandas(use_pyarrow_extension_array=True),
    "pyarrow": DF.to_arrow,
    "duckdb": lambda: duckdb.from_arrow(DF.to_arrow()),
    "spark-like": lambda: spark_like(DF),
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

    def test_blank_text_bound_is_open(self):
        # As the browser shows it: "name >= a", not also "<= '  '".
        settings = normalize_settings(
            {"filters": {"name": {"op": "range", "min": " a", "max": "  "}}}, SCHEMA
        )
        assert settings["filters"]["name"] == {
            "op": "range",
            "min": " a",  # text keeps its spaces
            "max": "",
            "case_sensitive": True,
        }

    def test_every_column_hidden_shows_them(self):
        # As the browser, which keeps a column shown.
        settings = normalize_settings({"hidden": list(SCHEMA)}, SCHEMA)
        assert settings["hidden"] == []


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
        return DataQuery(DF.lazy, "memory://data", store or ExplorerStates())

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
        query = DataQuery(source, "k", ExplorerStates())
        reply = query.handle({"type": "query_rows", "offset": 1, "window": 2})
        assert [row[:2] for row in reply["rows"]] == [["coffee", 5], ["Water", 1]]
        assert reply["more"] is True
        last = query.handle({"type": "query_rows", "offset": 2, "window": 2})
        assert [row[:2] for row in last["rows"]] == [["Water", 1], [None, 2]]
        assert last["more"] is False

    def test_paging_without_offsets(self):
        # pandas: rows are read up to the window's end and the first ones dropped.
        query = DataQuery(DF.to_pandas(), "k", ExplorerStates())
        assert query.lf.implementation.is_pandas()
        reply = query.handle({"type": "query_rows", "offset": 1, "window": 2})
        assert [row[0] for row in reply["rows"]] == ["coffee", "Water"]
        assert reply["more"] is True

    def test_missing_values_from_pandas(self):
        data = DF.to_pandas(use_pyarrow_extension_array=True)
        query = DataQuery(data, "k", ExplorerStates())
        reply = query.handle({"type": "query_rows", "offset": 3, "window": 1})
        assert reply["rows"] == [[None, 2, "2025-01-04", None]]

    def test_eager_data_queried_in_its_library(self):
        # As result() is: no other library needed, and filters behave alike.
        query = DataQuery(DF.to_pandas(), "k", ExplorerStates())
        assert query.lf.implementation.is_pandas()

    def test_pandas_nan_is_missing(self):
        # pandas marks missing text with NaN: shown as missing, as nulls are.
        data = DF.to_pandas()
        assert data["name"].isna().any()
        query = DataQuery(data, "k", ExplorerStates())
        reply = query.handle({"type": "query_rows", "offset": 3, "window": 1})
        assert reply["rows"][0][0] is None

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
        states = ExplorerStates()
        settings = {"sort": {"column": "price", "descending": False}}
        self.query(states).rows({"settings": settings})
        assert self.query(states).opening()["settings"]["sort"] == {
            "column": "price",
            "descending": False,
        }
        assert states.query("memory://data").mode == "auto"

    def test_mode_chosen_remembered(self):
        states = ExplorerStates()
        query = DataQuery(BIG.lazy, "k", states, max_live_rows=10)
        assert query.mode == "live"
        query.handle({"type": "query_mode", "mode": "memory", "settings": {}})
        # Remembered even with the default settings: the mode is not "auto".
        assert states.query("k").mode == "memory"

    def test_reload_fits_settings_to_new_columns(self):
        frames = iter([DF.lazy(), DF.drop("price").lazy()])
        query = DataQuery(lambda: next(frames), "k", ExplorerStates())
        reply = query.handle(
            {"type": "query_reload", "settings": {"hidden": ["price", "ok"]}}
        )
        assert [c["name"] for c in reply["columns"]] == ["name", "day", "ok"]
        assert reply["settings"]["hidden"] == ["ok"]

    def test_not_a_query_request(self):
        assert self.query().handle({"type": "preview"}) is None


BIG = pl.DataFrame({"n": list(range(50))})


def mode_query(source=BIG.lazy, **kwargs) -> DataQuery:
    kwargs.setdefault("max_live_rows", 10)
    kwargs.setdefault("max_memory_rows", 20)
    return DataQuery(source, "k", ExplorerStates(), **kwargs)


def rows_of(query: DataQuery, **content) -> dict:
    return query.handle({"type": "query_rows", "window": 1000, **content})


class TestModes:
    def test_auto_is_live_for_lazy_data(self):
        query = mode_query()
        assert query.mode_state() == {
            "mode": "live",
            "fixed": "",
            "memory": None,
            "partial": False,
            "live_limit": 20,  # max_memory_rows
            "max_memory_rows": 20,
        }
        reply = rows_of(query)
        assert (len(reply["rows"]), reply["limited"]) == (20, True)

    def test_small_lazy_data_kept_in_memory(self):
        query = mode_query(BIG.head(10).lazy, max_live_rows=10)
        state = query.mode_state()
        assert state["mode"] == "memory"
        assert state["memory"] == {"rows": 10, "cut": False}
        assert state["fixed"] == "All 10 rows are in memory."
        assert query.handle({"type": "query_mode", "mode": "live"})["error"]

    def test_explicit_live_on_small_data_too(self):
        assert mode_query(BIG.head(5).lazy, mode="live").mode == "memory"

    def test_memory_pages_share_one_result(self, monkeypatch):
        # Scrolling: pages of the same filters, sort and hidden columns are
        # cut from one result; other settings, or the data read again, make
        # a new one.
        built = []
        original = data_query.build_query

        def counted(*args):
            built.append(1)
            return original(*args)

        monkeypatch.setattr(data_query, "build_query", counted)
        query = mode_query(mode="memory")
        down = {"sort": {"column": "n", "descending": True}}
        pages = [rows_of(query, settings=down, offset=o, window=5) for o in (0, 5, 15)]
        assert [p["rows"][0] for p in pages] == [[19], [14], [4]]
        assert [p["more"] for p in pages] == [True, True, False]
        assert {p["total"] for p in pages} == {20}
        assert len(built) == 1
        rows_of(query, settings={**down, "widths": {"n": 80}})  # widths: same rows
        assert len(built) == 1
        filtered = rows_of(
            query, settings={"filters": {"n": {"op": "range", "max": 4}}}
        )
        assert (filtered["total"], len(built)) == (5, 2)
        query.reload({})
        rows_of(query, settings={"filters": {"n": {"op": "range", "max": 4}}})
        assert len(built) == 3

    def test_memory_mode_reads_the_first_rows(self):
        query = mode_query(mode="memory")
        assert query.mode_state()["memory"] == {"rows": 20, "cut": True}
        assert query.mode_state()["fixed"] == ""
        reply = rows_of(query, settings={"sort": {"column": "n", "descending": True}})
        # Sorting applies to the rows in memory only.
        assert reply["rows"][0] == [19] and len(reply["rows"]) == 20

    def test_eager_data_only_in_memory(self):
        query = mode_query(BIG.to_pandas())
        assert query.mode == "memory"
        assert query.memory == {"rows": 50, "cut": False}  # all of it, not limited
        assert query.fixed == "The data is a dataframe in memory."
        with pytest.raises(ValueError, match="live mode needs lazy data"):
            mode_query(BIG.to_pandas(), mode="live")

    def test_eager_data_of_the_first_rows(self):
        # The source read only the first rows (e.g. pandas, by a support):
        # noted as rows held in memory are.
        query = mode_query(BIG.to_pandas(), cut=lambda: True)
        assert query.memory == {"rows": 50, "cut": True}
        assert query.mode_state()["partial"] is False  # counted instead

    @pytest.mark.parametrize("mode", ["live", "memory"])
    def test_lazy_data_of_the_first_part(self, mode):
        # E.g. a file's first bytes: said in either mode, as live reads no more.
        query = mode_query(mode=mode, cut=lambda: True)
        assert query.mode_state()["partial"] is True
        assert mode_query(mode=mode).mode_state()["partial"] is False

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            mode_query(mode="online")

    def test_switching(self):
        query = mode_query(max_memory_rows=30)
        reply = query.handle({"type": "query_mode", "mode": "memory", "settings": {}})
        assert reply["mode"]["mode"] == "memory"
        assert reply["mode"]["memory"] == {"rows": 30, "cut": True}
        assert [c["name"] for c in reply["columns"]] == ["n"]
        live_from_40 = {"filters": {"n": {"op": "range", "min": "40", "max": ""}}}
        assert rows_of(query, settings=live_from_40)["rows"] == []  # not in memory
        reply = query.handle({"type": "query_mode", "mode": "live", "settings": {}})
        assert reply["mode"]["mode"] == "live"
        assert len(rows_of(query, settings=live_from_40)["rows"]) == 10

    def test_switching_back_from_complete_data_in_memory(self):
        # Chosen by the user, memory mode stays switchable even with all rows.
        query = mode_query(max_memory_rows=100)
        reply = query.handle({"type": "query_mode", "mode": "memory"})
        assert reply["mode"]["memory"] == {"rows": 50, "cut": False}
        assert reply["mode"]["fixed"] == ""
        assert (
            query.handle({"type": "query_mode", "mode": "live"})["mode"]["mode"]
            == "live"
        )

    def test_total_counted_in_memory_only(self):
        at_least_40 = {"filters": {"n": {"op": "range", "min": "40", "max": ""}}}
        live = mode_query()
        assert rows_of(live, window=5)["total"] is None
        memory = mode_query(mode="memory", max_memory_rows=100)
        reply = rows_of(memory, window=5, settings=at_least_40)
        assert (len(reply["rows"]), reply["total"]) == (5, 10)

    def test_reload_keeps_the_mode_chosen(self):
        query = mode_query()
        query.handle({"type": "query_mode", "mode": "memory"})
        assert query.handle({"type": "query_reload"})["mode"]["mode"] == "memory"

    def test_failed_reload_leaves_the_query_as_it_was(self):
        # The new data is given, then fails when its first rows are read.
        broken = BIG.lazy().select(pl.col("missing"))
        frames = iter([BIG.lazy(), broken])
        query = mode_query(lambda: next(frames))
        native = query.native
        assert "error" in query.handle({"type": "query_reload"})
        assert query.native is native
        assert rows_of(query, window=3)["rows"] == [[0], [1], [2]]

    def test_live_reload_of_data_now_eager(self):
        # "live" chosen for lazy data, which a reload gives as a dataframe:
        # queried in memory, as "auto" does, rather than failing each time.
        frames = iter([BIG.lazy(), BIG])
        query = mode_query(lambda: next(frames), mode="live")
        reply = query.handle({"type": "query_reload"})
        assert "error" not in reply
        assert reply["mode"]["fixed"] == "The data is a dataframe in memory."

    def test_live_limit(self):
        reads = []

        def fetch(lf, offset, length):
            reads.append((offset, length))
            return data_query.fetch_rows(lf, offset, length)

        query = mode_query(lambda: duckdb.from_arrow(BIG.to_arrow()), fetch=fetch)
        assert query.mode_state()["live_limit"] == 20  # max_memory_rows
        first = rows_of(query, window=4)
        assert first["rows"] == [[0], [1], [2], [3]] and first["more"] is True
        last = rows_of(query, offset=16, window=8)
        assert last["rows"] == [[16], [17], [18], [19]]
        assert (last["more"], last["limited"]) == (False, True)
        # Pages read through fetch, with one row more: is there more, or a limit?
        # The first rows when opening (max_live_rows + 1), then the pages.
        assert reads == [(0, 11), (0, 5), (16, 5)]
        # A result within the limit is not limited.
        small = rows_of(
            query, settings={"filters": {"n": {"op": "range", "min": "45", "max": ""}}}
        )
        assert (len(small["rows"]), small["limited"]) == (5, False)


class TestSparkLike:
    """Spark (here sqlframe, see ``spark_like``): no offsets, all rows before
    each page are read; at most ``max_memory_rows`` rows, as for all data."""

    def query(self, rows: int = 50, **kwargs) -> DataQuery:
        return mode_query(spark_like(BIG.head(rows)), **kwargs)

    def test_live_with_a_limit(self):
        query = self.query()
        assert query.lf.implementation.is_spark_like()
        assert query.mode_state()["live_limit"] == 20
        desc = {"sort": {"column": "n", "descending": True}}
        first = rows_of(query, window=4, settings=desc)
        assert first["rows"] == [[49], [48], [47], [46]]
        assert (first["more"], first["limited"], first["total"]) == (True, False, None)
        last = rows_of(query, offset=16, window=4, settings=desc)
        assert last["rows"] == [[33], [32], [31], [30]]
        assert (last["more"], last["limited"]) == (False, True)

    def test_filtered_result_within_the_limit(self):
        f = {"filters": {"n": {"op": "range", "min": "45", "max": ""}}}
        reply = rows_of(self.query(), settings=f)
        assert reply["rows"] == [[45], [46], [47], [48], [49]]
        assert (reply["more"], reply["limited"]) == (False, False)

    def test_in_memory(self):
        # In the library narwhals collects Spark's rows into, not Spark.
        query = self.query()
        reply = query.handle({"type": "query_mode", "mode": "memory"})
        assert reply["mode"]["memory"] == {"rows": 20, "cut": True}
        assert not query.lf.implementation.is_spark_like()
        assert rows_of(query, window=5)["total"] == 20
        f = {"filters": {"n": {"op": "range", "min": "15", "max": ""}}}
        assert rows_of(query, settings=f)["rows"] == [[15], [16], [17], [18], [19]]

    def test_small_data_kept_in_memory(self):
        query = self.query(rows=8)
        assert query.mode == "memory"
        assert query.fixed == "All 8 rows are in memory."

    def test_bad_regex_reported_with_the_rows(self):
        f = {"op": "regex", "value": "("}
        query = mode_query(spark_like(DF), max_live_rows=2)  # 4 rows: live
        # No one-row table to try the pattern on beforehand...
        assert query.check({"column": "name", "filter": f}) == {}
        # ...so the error comes with the rows.
        assert "error" in rows_of(query, settings={"filters": {"name": f}})


class TestReads:
    """Every read of lazy data, the first rows when opening and each live
    page, goes through the query's fetch, then fetch_rows. An explorer's
    fetch is the user's, then the view's (a support's)."""

    @staticmethod
    def recording(name, reads, give=True):
        def fetch(lf, offset, length):
            reads.append((name, offset, length))
            return data_query.fetch_rows(lf, offset, length) if give else None

        return fetch

    def test_the_fetch_first(self):
        reads = []
        rows_of(mode_query(fetch=self.recording("fetch", reads)), offset=5, window=2)
        assert reads == [("fetch", 0, 11), ("fetch", 5, 3)]

    def test_the_default_when_the_fetch_gives_none(self):
        reads = []
        query = mode_query(fetch=self.recording("fetch", reads, give=False))
        reply = rows_of(query, offset=5, window=2)
        assert reply["rows"] == [[5], [6]]
        assert len(reads) == 2

    def test_the_default_without_fetch(self):
        reply = rows_of(mode_query(), offset=5, window=2)
        assert reply["rows"] == [[5], [6]]

    def test_reading_into_memory(self):
        reads = []
        mode_query(mode="memory", fetch=self.recording("fetch", reads))
        assert reads == [("fetch", 0, 21)]  # max_memory_rows + 1

    def test_an_explorers_the_users_first(self):
        reads = []
        user = self.recording("user", reads)
        fetch = _layered_fetch(user, lambda: self.recording("view", reads))
        rows_of(mode_query(fetch=fetch), offset=5, window=2)
        assert [name for name, *_ in reads] == ["user", "user"]

    def test_an_explorers_the_views_when_the_user_gives_none(self):
        reads = []
        user = self.recording("user", reads, give=False)
        fetch = _layered_fetch(user, lambda: self.recording("view", reads))
        reply = rows_of(mode_query(fetch=fetch), offset=5, window=2)
        assert reply["rows"] == [[5], [6]]
        assert [name for name, *_ in reads] == ["user", "view", "user", "view"]

    def test_an_explorers_the_default_without_either(self):
        fetch = _layered_fetch(None, lambda: None)
        reply = rows_of(mode_query(fetch=fetch), offset=5, window=2)
        assert reply["rows"] == [[5], [6]]


class TestDaskRows:
    """Dask's rows are read partition by partition, until there are enough:
    narwhals' head would read every partition."""

    @pytest.fixture
    def frame(self):
        dd = pytest.importorskip("dask.dataframe")
        computed = []

        def partition(i):
            computed.append(i)
            return pd.DataFrame({"n": range(i * 10, i * 10 + 10)})

        meta = pd.DataFrame({"n": pd.Series(dtype="int64")})
        return dd.from_map(partition, range(5), meta=meta), computed

    def test_first_partitions_only(self, frame):
        ddf, computed = frame
        lf = nw.from_native(ddf)
        assert data_query.fetch_rows(lf, 0, 5)["n"].to_list() == [0, 1, 2, 3, 4]
        assert computed == [0]
        computed.clear()
        page = data_query.fetch_rows(lf, 15, 10)["n"].to_list()
        assert page == list(range(15, 25))
        assert computed == [0, 1, 2]

    def test_sorted_in_one_pass(self, frame):
        # Computed one by one, each partition of sorted data would sort all
        # of it again: Dask's head of every partition reads each once.
        ddf, computed = frame
        lf = nw.from_native(ddf).sort("n", descending=True)
        page = data_query.fetch_rows(lf, 15, 10)["n"].to_list()
        assert page == list(range(34, 24, -1))
        assert sorted(computed) == [0, 1, 2, 3, 4]

    def test_beyond_the_end(self, frame):
        ddf, _ = frame
        assert len(data_query.fetch_rows(nw.from_native(ddf), 45, 10)) == 5

    def test_opening_reads_the_first_partitions(self, frame):
        ddf, computed = frame
        query = mode_query(ddf)  # max_live_rows 10: 11 rows, two partitions
        assert query.mode == "live"
        assert sorted(set(computed)) == [0, 1]
        reply = rows_of(query, settings={"filters": {"n": {"op": "range", "min": 42}}})
        assert [row[0] for row in reply["rows"]] == list(range(42, 50))
