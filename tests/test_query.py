"""query.py: the data browser's settings, filters, paging and remembered settings."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

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
SCHEMA = DF.schema


def run(settings: dict) -> pl.DataFrame:
    return build_query(
        DF.lazy(), SCHEMA, normalize_settings(settings, SCHEMA)
    ).collect()


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
    def test_contains_ignoring_case(self):
        df = run(
            {
                "filters": {
                    "name": {"op": "contains", "value": "TE", "case_sensitive": False}
                }
            }
        )
        assert df["name"].to_list() == ["Tea", "Water"]

    def test_regex(self):
        df = run({"filters": {"name": {"op": "regex", "value": "^[A-Z]"}}})
        assert df["name"].to_list() == ["Tea", "Water"]

    def test_numeric_range_open_end(self):
        df = run({"filters": {"price": {"op": "range", "min": "2", "max": ""}}})
        assert df["price"].to_list() == [3, 5, 2]

    def test_date_range(self):
        df = run(
            {
                "filters": {
                    "day": {"op": "range", "min": "2025-01-02", "max": "2025-01-03"}
                }
            }
        )
        assert df["price"].to_list() == [5, 1]

    def test_null(self):
        assert run({"filters": {"name": {"op": "null"}}})["price"].to_list() == [2]

    def test_boolean(self):
        assert run({"filters": {"ok": {"op": "eq", "value": "yes"}}})[
            "price"
        ].to_list() == [3, 1]

    def test_sort_nulls_last_and_hidden(self):
        df = run(
            {"sort": {"column": "name", "descending": True}, "hidden": ["day", "ok"]}
        )
        assert df.columns == ["name", "price"]
        assert df["name"].to_list() == ["coffee", "Water", "Tea", None]

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


class TestDataQuery:
    def query(self, store=None) -> DataQuery:
        return DataQuery(DF.lazy, "memory://data", store or QuerySettingsStore())

    def test_paging(self):
        reply = self.query().handle({"type": "query_rows", "offset": 1, "window": 2})
        assert reply["rows"] == [
            ["coffee", 5, "2025-01-02", False],
            ["Water", 1, "2025-01-03", True],
        ]
        assert reply["more"] is True
        last = self.query().handle({"type": "query_rows", "offset": 2, "window": 2})
        assert last["more"] is False

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
