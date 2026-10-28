"""DataExplorer: a dataframe in the data browser, its options and settings."""

from __future__ import annotations

import asyncio
import datetime as dt
import threading
from typing import Any

import duckdb
import polars as pl
import pytest
from in_a_kernel import until
from sqlframe.duckdb import DuckDBSession

from jupyter_storage_explorer import DataExplorer, QuerySettings
from jupyter_storage_explorer._query.data_query import fetch_rows

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
    assert (explorer._title, explorer._library) == ("LazyFrame", "polars")
    assert [c["name"] for c in explorer._query["columns"]] == ["a", "b"]
    reply = explorer.request({"type": "query_rows", "offset": 2, "window": 5})
    assert reply == {
        "type": "reply",
        "rid": 1,
        "offset": 2,
        "rows": [[2, None]],
        "more": False,
        "limited": False,
        "total": 3,  # 3 rows: kept in memory, where they are counted
        "settings": explorer._query["settings"],
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
    assert (explorer._library, explorer._title) == (library, title)
    assert explorer._query["mode"]["mode"] == "memory"
    assert explorer._query["mode"]["fixed"]
    with pytest.raises(ValueError, match="live mode needs lazy data"):
        Explorer(data, mode="live")


def test_duckdb_with_options():
    data = duckdb.from_arrow(pl.DataFrame({"n": list(range(30))}).to_arrow())
    explorer = Explorer(data, max_live_rows=10, max_memory_rows=20, title="Numbers")
    assert (explorer._title, explorer._library) == ("Numbers", "DuckDB")
    assert explorer._query["mode"]["mode"] == "live"
    reply = explorer.request({"type": "query_mode", "mode": "memory"})
    assert reply["mode"]["memory"] == {"rows": 20, "cut": True}


def test_spark_like_dataframe():
    # sqlframe stands in for Spark (which needs Java); narwhals treats both alike.
    data = DuckDBSession().createDataFrame([(i,) for i in range(30)], schema="n bigint")
    explorer = Explorer(data, max_live_rows=10)
    assert (explorer._title, explorer._library) == ("DuckDBDataFrame", "SQLFrame")
    assert explorer._query["mode"]["mode"] == "live"
    assert explorer._query["mode"]["live_limit"] == 100_000  # max_memory_rows


def test_fetch_rows_given():
    fetched = []

    def fetch(lf, offset, length):
        fetched.append((offset, length))
        return fetch_rows(lf, offset, length)

    data = DuckDBSession().createDataFrame([(i,) for i in range(30)], schema="n bigint")
    explorer = Explorer(data, max_live_rows=10, fetch_rows=fetch)
    reply = explorer.request({"type": "query_rows", "offset": 25, "window": 10})
    assert reply["rows"] == [[25], [26], [27], [28], [29]]
    # The first rows when opening, then the page: one extra row tells whether
    # there are more.
    assert fetched == [(0, 11), (25, 11)]
    # Reading into memory goes through it too (max_memory_rows + 1); the rows
    # in memory (collected into another library) are then sliced.
    explorer.request({"type": "query_mode", "mode": "memory"})
    reply = explorer.request({"type": "query_rows", "offset": 25, "window": 10})
    assert len(reply["rows"]) == 5
    assert fetched == [(0, 11), (25, 11), (0, 100_001)]


def test_fetch_rows_none_reads_the_default_way():
    data = DuckDBSession().createDataFrame([(i,) for i in range(30)], schema="n bigint")
    explorer = Explorer(data, max_live_rows=10, fetch_rows=lambda lf, o, n: None)
    reply = explorer.request({"type": "query_rows", "offset": 25, "window": 10})
    assert reply["rows"] == [[25], [26], [27], [28], [29]]


def test_function_called_again_on_reload():
    frames = iter([DF.lazy(), DF.drop("b").lazy()])
    explorer = Explorer(lambda: next(frames))
    reply = explorer.request({"type": "query_reload"})
    assert [c["name"] for c in reply["columns"]] == ["a"]


@pytest.mark.parametrize(
    "given",
    [
        QuerySettings(sort="a", descending=True, hidden=["b"]),
        {"sort": {"column": "a", "descending": True}, "hidden": ["b"]},
        '{"sort": {"column": "a", "descending": true}, "hidden": ["b"]}',
    ],
)
def test_settings_as_dict_or_json(given):
    explorer = Explorer(DF.lazy(), settings=given)
    assert explorer.settings == QuerySettings(sort="a", descending=True, hidden=["b"])


@pytest.mark.parametrize(
    ("given", "error"), [("[1]", ValueError), ("{", ValueError), (3, TypeError)]
)
def test_settings_of_another_form(given, error):
    with pytest.raises(error):
        Explorer(DF.lazy(), settings=given)


def test_settings_in_and_out():
    settings = QuerySettings(
        filters={"a": {"op": "range", "min": 2}},
        sort="a",
        descending=True,
        hidden=["gone"],  # not a column: left out
    )
    explorer = Explorer(DF.lazy(), settings=settings)
    assert explorer._query["settings"]["filters"] == {
        "a": {"op": "range", "min": "2", "max": ""}
    }
    reply = explorer.request(
        {"type": "query_rows", "window": 10, "settings": explorer._query["settings"]}
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
        assert explorer._query["mode"]["memory"] == {"rows": 10, "cut": True}
        # The widget showed rows 0-9 only; the result covers all 100.
        assert explorer.result().collect()["a"].to_list()[:3] == [99, 98, 97]

    def test_all_columns(self):
        """The widget's filters and sort order, with the columns it hides."""
        result = self.explorer(DF.lazy()).result(all_columns=True).collect()
        assert result.to_dict(as_series=False) == {"a": [3, 2], "b": ["x", None]}

    def test_without_changes(self):
        assert Explorer(DF).result().equals(DF)

    def test_from_settings_given(self):
        explorer = Explorer(DF.lazy(), settings=QuerySettings(hidden=["a"]))
        assert explorer.result().collect_schema().names() == ["b"]


class TestOnChange:
    """explorer.on_change(): told when result() changes in the widget."""

    def explorer(self, data: Any = None, **kwargs) -> tuple[Explorer, list[Any]]:
        explorer = Explorer(DF.lazy() if data is None else data, **kwargs)
        calls: list[Any] = []
        explorer.on_change(lambda e: calls.append(e.result().collect()["a"].to_list()))
        return explorer, calls

    def test_filters_sort_and_columns(self):
        explorer, calls = self.explorer()
        # The rows first shown, with the settings it started with: no change.
        explorer.request(
            {"type": "query_rows", "settings": explorer._query["settings"]}
        )
        assert calls == []
        explorer.request({"type": "query_rows", "settings": RESULT_SETTINGS})
        assert calls == [[3, 2]]
        explorer.request({"type": "query_rows", "settings": {"sort": {"column": "a"}}})
        assert calls == [[3, 2], [1, 2, 3]]

    def test_not_for_what_leaves_the_result(self):
        explorer, calls = self.explorer()
        settings = {**RESULT_SETTINGS, "widths": {"a": 80}}
        explorer.request({"type": "query_rows", "settings": RESULT_SETTINGS})
        explorer.request({"type": "query_save", "settings": settings})  # widths
        explorer.request({"type": "query_rows", "settings": settings, "offset": 1})
        explorer.request({"type": "query_mode", "mode": "memory", "settings": settings})
        explorer.request(
            {"type": "query_check", "column": "a", "filter": {"op": "null"}}
        )
        assert calls == [[3, 2]]

    def test_reload(self):
        frames = iter([DF.lazy(), DF.head(1).lazy()])
        explorer, calls = self.explorer(lambda: next(frames))
        explorer.request({"type": "query_reload"})
        assert calls == [[3]]

    def test_remove(self):
        explorer, calls = self.explorer()
        callback = explorer._change_callbacks._functions[0]
        explorer.on_change(callback)  # once only
        explorer.request({"type": "query_rows", "settings": {"hidden": ["b"]}})
        explorer.on_change(callback, remove=True)
        explorer.request({"type": "query_rows", "settings": {}})
        assert calls == [[3, 1, 2]]

    def test_error_after_the_reply(self, monkeypatch, caplog):
        """A failing function: the widget has its rows, and the other functions
        are called; outside IPython, the error is raised."""
        explorer, calls = self.explorer()

        def fail(_explorer: Any) -> None:
            raise RuntimeError("chart failed")

        explorer._change_callbacks._functions.insert(0, fail)
        with pytest.raises(RuntimeError, match="chart failed"):
            explorer.request({"type": "query_rows", "settings": {"hidden": ["b"]}})
        assert explorer.sent[-1]["rows"] == [[3], [1], [2]]

        # In IPython, called back by the page, and logged with its traceback:
        # the other functions still run.
        monkeypatch.setattr("IPython.get_ipython", object)  # a shell of any kind
        caplog.clear()
        explorer.request({"type": "query_rows", "settings": {}})
        assert explorer.sent[-1] == {"type": "callbacks", "name": "change"}
        assert calls == []
        explorer.request({"type": "callbacks", "name": "change"})
        [record] = [r for r in caplog.records if r.levelname == "ERROR"]
        assert "given to the widget failed" in record.getMessage()
        assert record.exc_info is not None
        assert calls == [[3, 1, 2]]

    def test_called_back_by_the_page_in_ipython(self, monkeypatch):
        """In IPython, the page calls the functions back, so that an Output's
        with block shows what they display: once for several changes, and once
        however many views of the widget answer."""
        explorer, calls = self.explorer()
        monkeypatch.setattr("IPython.get_ipython", object)
        explorer.request({"type": "query_rows", "settings": RESULT_SETTINGS})
        explorer.request({"type": "query_rows", "settings": {"hidden": ["b"]}})
        asked = [m for m in explorer.sent if m.get("type") == "callbacks"]
        assert asked == [{"type": "callbacks", "name": "change"}]
        assert calls == []
        explorer.request({"type": "callbacks", "name": "change"})
        explorer.request({"type": "callbacks", "name": "change"})  # another view
        assert calls == [[3, 1, 2]]


def test_requests_in_a_worker_in_order():
    # In a kernel, a page read slowly (e.g. a Spark job) leaves the kernel
    # free; the replies come in the order asked, one request at a time.
    release = threading.Event()
    threads = []
    holding = []  # the pages only, not the first rows read when opening

    def held(lf, offset, length):
        if not holding:
            return None
        threads.append(threading.current_thread())
        assert release.wait(5)

    async def main():
        explorer = Explorer(DF.lazy(), mode="live", fetch_rows=held)
        holding.append(True)
        explorer.sent = []
        for rid in (1, 2):
            explorer._on_custom_msg(
                explorer, {"type": "query_rows", "rid": rid, "window": 2}, None
            )
        assert explorer.sent == []  # still reading
        release.set()
        await until(lambda: len(explorer.sent) == 2)
        return explorer.sent

    sent = asyncio.run(main())
    assert [reply["rid"] for reply in sent] == [1, 2]
    assert sent[0]["rows"] == [[3, "x"], [1, "y"]]
    assert threading.main_thread() not in threads


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
            {"type": "query_rows", "settings": explorer._query["settings"]}
        )
        assert reply["rows"] == [[0, "2025-01-01"], [1, "2025-01-02"]]
