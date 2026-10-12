"""DataExplorer: a dataframe in the data browser, its options and settings."""

from __future__ import annotations

import datetime as dt
from typing import Any

import duckdb
import polars as pl
import pytest
from sqlframe.duckdb import DuckDBSession

from jupyter_storage_explorer import DataExplorer, QuerySettings

DF = pl.DataFrame({"a": [3, 1, 2], "b": ["x", "y", None]})


class Explorer(DataExplorer):
    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        self.__dict__.setdefault("sent", []).append(content)

    def request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Send a request as the frontend does; the reply."""
        self._on_custom_msg(self, {"rid": 1, **content}, None)
        return self.sent[-1]


def test_lazy_frame():
    explorer = Explorer(DF.lazy())
    assert (explorer.title, explorer.library) == ("LazyFrame", "polars")
    assert [c["name"] for c in explorer.query["columns"]] == ["a", "b"]
    reply = explorer.request({"type": "query_rows", "offset": 2, "window": 5})
    assert reply == {
        "type": "reply",
        "rid": 1,
        "offset": 2,
        "columns": ["a", "b"],
        "dtypes": ["Int64", "String"],
        "rows": [[2, None]],
        "more": False,
        "limited": False,
        "total": 3,  # 3 rows: kept in memory, where they are counted
        "settings": explorer.query["settings"],
    }


@pytest.mark.parametrize(
    ("data", "library", "title"),
    [
        (DF.to_pandas(), "pandas", "DataFrame"),
        (DF.to_arrow(), "PyArrow", "Table"),
        (DF, "polars", "DataFrame"),
    ],
)
def test_eager_dataframes(data, library, title):
    explorer = Explorer(data)
    assert (explorer.library, explorer.title) == (library, title)
    assert explorer.query["mode"]["mode"] == "memory"
    assert explorer.query["mode"]["fixed"]
    with pytest.raises(ValueError, match="live mode needs lazy data"):
        Explorer(data, mode="live")


def test_duckdb_with_options():
    data = duckdb.from_arrow(pl.DataFrame({"n": list(range(30))}).to_arrow())
    explorer = Explorer(data, max_live_rows=10, max_memory_rows=20, title="Numbers")
    assert (explorer.title, explorer.library) == ("Numbers", "DuckDB")
    assert explorer.query["mode"]["mode"] == "live"
    reply = explorer.request({"type": "query_mode", "mode": "memory"})
    assert reply["mode"]["memory"] == {"rows": 20, "cut": True}


def test_spark_like_dataframe():
    # sqlframe stands in for Spark (which needs Java); narwhals treats both alike.
    data = DuckDBSession().createDataFrame([(i,) for i in range(30)], schema="n bigint")
    explorer = Explorer(data, max_live_rows=10)
    assert (explorer.title, explorer.library) == ("DuckDBDataFrame", "SQLFrame")
    assert explorer.query["mode"]["mode"] == "live"
    assert explorer.query["mode"]["live_limit"] == 10


def test_function_called_again_on_reload():
    frames = iter([DF.lazy(), DF.drop("b").lazy()])
    explorer = Explorer(lambda: next(frames))
    reply = explorer.request({"type": "query_reload"})
    assert [c["name"] for c in reply["columns"]] == ["a"]


def test_settings_in_and_out():
    settings = QuerySettings(
        filters={"a": {"op": "range", "min": 2}},
        sort="a",
        descending=True,
        hidden=["gone"],  # not a column: left out
    )
    explorer = Explorer(DF.lazy(), settings=settings)
    assert explorer.query["settings"]["filters"] == {
        "a": {"op": "range", "min": "2", "max": ""}
    }
    reply = explorer.request(
        {"type": "query_rows", "window": 10, "settings": explorer.query["settings"]}
    )
    assert reply["rows"] == [[3, "x"], [2, None]]
    assert explorer.settings == QuerySettings(
        filters={"a": {"op": "range", "min": "2", "max": ""}},
        sort="a",
        descending=True,
    )
    # Changed in the widget: the property follows.
    explorer.request(
        {"type": "query_rows", "settings": {"sort": {"column": "b"}, "hidden": ["a"]}}
    )
    assert explorer.settings == QuerySettings(sort="b", hidden=["a"])


def test_settings_kept_per_explorer():
    first = Explorer(DF.lazy())
    first.request({"type": "query_rows", "settings": {"hidden": ["b"]}})
    assert Explorer(DF.lazy()).settings == QuerySettings()


# Settings as the user might make them in the widget.
RESULT_SETTINGS = {
    "filters": {"a": {"op": "range", "min": "2", "max": ""}},
    "sort": {"column": "a", "descending": True},
    "hidden": ["b"],
}


class TestResult:
    """explorer.result(): the data with the widget's settings applied."""

    def explorer(self, data: Any, **kwargs) -> Explorer:
        explorer = Explorer(data, **kwargs)
        # As the frontend does when the user changes the settings.
        explorer.request({"type": "query_rows", "settings": RESULT_SETTINGS})
        return explorer

    def test_lazy_stays_lazy(self):
        result = self.explorer(DF.lazy()).result()
        assert isinstance(result, pl.LazyFrame)
        assert result.collect().to_dict(as_series=False) == {"a": [3, 2]}

    def test_eager_is_computed(self):
        result = self.explorer(DF.to_pandas()).result()
        assert type(result).__module__.startswith("pandas")
        assert result["a"].tolist() == [3, 2]
        assert list(result.columns) == ["a"]

    def test_spark_like_stays_spark_like(self):
        data = DuckDBSession().createDataFrame(DF.rows(), schema="a bigint, b string")
        result = self.explorer(data).result()
        assert type(result) is type(data)
        assert [row[0] for row in result.collect()] == [3, 2]

    def test_all_the_data_after_memory_mode(self):
        data = pl.LazyFrame({"a": list(range(100)), "b": ["x"] * 100})
        explorer = self.explorer(data, mode="memory", max_memory_rows=10)
        assert explorer.query["mode"]["memory"] == {"rows": 10, "cut": True}
        # The widget showed rows 0-9 only; the result covers all 100.
        assert explorer.result().collect()["a"].to_list()[:3] == [99, 98, 97]

    def test_without_changes(self):
        assert Explorer(DF).result().equals(DF)

    def test_from_settings_given(self):
        explorer = Explorer(DF.lazy(), settings=QuerySettings(hidden=["a"]))
        assert explorer.result().collect_schema().names() == ["b"]


def test_not_a_dataframe():
    with pytest.raises(TypeError, match="takes a dataframe, not a location"):
        Explorer("data/orders.csv")
    with pytest.raises(TypeError, match="needs a dataframe narwhals supports"):
        Explorer([1, 2, 3])


class TestQuerySettings:
    def test_round_trip(self):
        settings = QuerySettings(
            filters={"b": {"op": "null"}}, sort="a", hidden=["b"], widths={"a": 90}
        )
        assert settings.to_dict() == {
            "filters": {"b": {"op": "null"}},
            "sort": {"column": "a", "descending": False},
            "hidden": ["b"],
            "widths": {"a": 90},
        }
        assert QuerySettings.from_dict(settings.to_dict()) == settings

    def test_json(self):
        settings = QuerySettings(
            filters={"d": {"op": "range", "min": dt.date(2025, 1, 2)}},
            sort="a",
            descending=True,
        )
        text = settings.to_json()
        assert text.startswith('{\n    "filters": {')  # indented by 4
        assert '"min": "2025-01-02"' in text  # dates as ISO text
        assert QuerySettings.from_json(text) == QuerySettings(
            filters={"d": {"op": "range", "min": "2025-01-02"}},
            sort="a",
            descending=True,
        )
        assert "\n" not in settings.to_json(indent=None)
        with pytest.raises(ValueError, match="JSON object"):
            QuerySettings.from_json("[]")

    def test_values_from_python(self):
        df = pl.DataFrame(
            {"n": [0, 1, -1], "d": [dt.date(2025, 1, d) for d in (1, 2, 3)]}
        )
        settings = QuerySettings(
            filters={
                "n": {"op": "range", "min": 0},  # 0 is a bound, not "none"
                "d": {"op": "range", "max": dt.date(2025, 1, 2)},
            }
        )
        explorer = Explorer(df, settings=settings)
        reply = explorer.request(
            {"type": "query_rows", "settings": explorer.query["settings"]}
        )
        assert reply["rows"] == [[0, "2025-01-01"], [1, "2025-01-02"]]
