"""pandas-support: its actions' views (pandas reads through the item's
fsspec filesystem, eagerly: the first max_memory_rows rows) and code, and its
entry point."""

from __future__ import annotations

import io
import json
from importlib.metadata import entry_points

import pandas as pd
import pytest
from jupyter_storage_explorer_pandas_support import (
    PANDAS_ACTIONS,
    CsvByPandasOptions,
    ExcelByPandasOptions,
    JsonByPandasOptions,
    JsonLinesByPandasOptions,
    PandasOptions,
    PandasSupport,
    ParquetByPandasOptions,
    csv_as_data_frame,
    csv_view,
    excel_view,
    json_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
)

from jupyter_storage_explorer.formats import Csv, Excel, Json, JsonLines, Parquet
from jupyter_storage_explorer.views import QueryView, TableSetView, ViewLimits

LIMITS = ViewLimits(max_display_rows=2)
# pandas reads at most max_memory_rows rows.
PANDAS_LIMITS = ViewLimits(max_memory_rows=2)


def parquet_bytes(columns: dict) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(columns).to_parquet(buffer, index=False)
    return buffer.getvalue()


def workbook() -> bytes:
    """Two sheets: "one", a column "a" of 1, 2, 3; "two", a column "b"."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(writer, sheet_name="one", index=False)
        pd.DataFrame({"b": [1]}).to_excel(writer, sheet_name="two", index=False)
    return buffer.getvalue()


def last_line(code: str) -> str:
    return code.strip().splitlines()[-1]


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="pandas-support"
    )
    plugin = entry_point.load()()
    assert isinstance(plugin, PandasSupport)
    assert plugin.description == "pandas support for Storage Explorer"
    assert plugin.actions == PANDAS_ACTIONS
    assert csv_view in plugin.actions


def test_one_options_class_per_format():
    # A format's view and code take the same options.
    by_format: dict[type, set[type]] = {}
    for action in PANDAS_ACTIONS:
        by_format.setdefault(action.format, set()).add(action.options_model)
    assert all(len(models) == 1 for models in by_format.values())


class TestViews:
    def test_csv(self, make_item):
        item = make_item("/a.csv", b"x;y\n1;2\n3;4\n5;6\n")
        query = csv_view(Csv(), item, PandasOptions(), PANDAS_LIMITS)
        assert isinstance(query, QueryView)
        assert list(query.data.columns) == ["x", "y"]  # the separator detected
        assert query.data.values.tolist() == [[1, 2], [3, 4]]
        assert query.more

    def test_json_lines(self, make_item):
        lines = b"".join(json.dumps({"i": i}).encode() + b"\n" for i in range(5))
        item = make_item("/a.jsonl", lines)
        query = json_lines_view(JsonLines(), item, PandasOptions(), PANDAS_LIMITS)
        assert query.data["i"].tolist() == [0, 1]
        assert query.more

    def test_parquet_file(self, make_item):
        # pyarrow reads through the item's fsspec filesystem, so memory:// works.
        item = make_item("/a.parquet", parquet_bytes({"a": [1, 2, 3]}))
        query = parquet_view(Parquet(), item, PandasOptions(), PANDAS_LIMITS)
        assert query.data["a"].tolist() == [1, 2]
        assert query.more
        whole = parquet_view(Parquet(), item, PandasOptions(), LIMITS)
        assert (whole.data["a"].tolist(), whole.more) == ([1, 2, 3], False)

    def test_partitioned_parquet(self, make_item, memfs):
        for year in (2025, 2026):
            data = parquet_bytes({"a": [year, year]})
            memfs.pipe_file(f"/t/year={year}/part-0.parquet", data)
        fmt = Parquet()
        item = make_item("/t")
        assert fmt.matches(item)
        query = parquet_view(fmt, item, PandasOptions(), LIMITS)
        # Every partition, its column from the folders' names.
        assert list(query.data.columns) == ["a", "year"]
        assert query.data["year"].astype(int).tolist() == [2025, 2025, 2026, 2026]

    def test_excel_sheets_on_tabs(self, make_item):
        item = make_item("/a.xlsx", workbook())
        view = excel_view(Excel(), item, PandasOptions(), PANDAS_LIMITS)
        assert isinstance(view, TableSetView)
        assert view.selector == "tab"
        assert [leaf.id for leaf in view.leaves()] == ["one", "two"]
        # Each sheet's first rows, as QueryViews telling whether there are more.
        one, two = view.loader("one"), view.loader("two")
        assert (one.data["a"].tolist(), one.more) == ([1, 2], True)
        assert (two.data["b"].tolist(), two.more) == ([1], False)

    def test_excel_with_one_sheet(self, make_item):
        buffer = io.BytesIO()
        pd.DataFrame({"a": [1]}).to_excel(buffer, sheet_name="only", index=False)
        item = make_item("/a.xlsx", buffer.getvalue())
        query = excel_view(Excel(), item, PandasOptions(), PANDAS_LIMITS)
        assert isinstance(query, QueryView)
        assert query.data["a"].tolist() == [1]


class TestCode:
    def test_csv(self, make_item):
        code = csv_as_data_frame(Csv(), make_item("/a.tsv", b"x\ty\n"), PandasOptions())
        assert code.startswith("import pandas as pd")
        assert last_line(code) == "df = pd.read_csv('memory:///a.tsv', sep='\\t')"

    def test_partitioned_parquet(self, make_item, memfs):
        # pyarrow finds partitions itself.
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        code = parquet_as_data_frame(Parquet(), make_item("/t"), PandasOptions())
        assert last_line(code) == "df = pd.read_parquet('memory:///t')"

    def test_storage_options_without_secrets(self, make_item):
        options = PandasOptions(storage_options={"account_key": "k", "anon": True})
        code = csv_as_data_frame(Csv(), make_item("/a.csv", b"a\n"), options)
        assert last_line(code) == (
            "df = pd.read_csv('memory:///a.csv', storage_options={'anon': True})"
        )

    def test_names(self):
        assert [a.label for a in PANDAS_ACTIONS if a.format is Parquet] == [
            "View as Parquet (pandas)",
            "Load as DataFrame",
        ]


class TestReaderOptions:
    """Each format's options are its reader's arguments, given or left to
    pandas."""

    def test_csv_arguments_in_the_data_browser(self, make_item):
        item = make_item("/a.csv", b"x;y\n1;NA\n2;3\n4;5\n")
        options = CsvByPandasOptions(usecols=["y"], na_values=["NA"], nrows=10)
        query = csv_view(Csv(), item, options, PANDAS_LIMITS)
        # The separator still detected; nrows at most the data browser's.
        assert list(query.data.columns) == ["y"]
        assert query.data["y"].isna().tolist() == [True, False]
        assert query.more

    def test_csv_arguments_in_the_code(self, make_item):
        options = CsvByPandasOptions(sep="|", header=None, dtype={"a": "string"})
        code = csv_as_data_frame(Csv(), make_item("/a.csv", b"x;y\n"), options)
        # The separator given, not the one detected; None, a value given, shown.
        assert last_line(code) == (
            "df = pd.read_csv('memory:///a.csv', sep='|', header=None,"
            " dtype={'a': 'string'})"
        )

    def test_json_lines_encoding(self, make_item):
        item = make_item("/a.jsonl", '{"s": "é"}\n'.encode("latin-1"))
        options = JsonLinesByPandasOptions(encoding="latin-1")
        query = json_lines_view(JsonLines(), item, options, PANDAS_LIMITS)
        assert query.data["s"].tolist() == ["é"]

    def test_json_code(self, make_item):
        options = JsonByPandasOptions(orient="records")
        code = json_as_data_frame(Json(), make_item("/a.json", b"[]"), options)
        assert (
            last_line(code) == "df = pd.read_json('memory:///a.json', orient='records')"
        )

    def test_excel_sheet(self, make_item):
        item = make_item("/a.xlsx", workbook())
        options = ExcelByPandasOptions(sheet_name="two")
        query = excel_view(Excel(), item, options, PANDAS_LIMITS)
        assert list(query.data.columns) == ["b"]

    @pytest.mark.parametrize("sheet_name", [None, ["two", "one"]])
    def test_excel_sheets_asked_for_on_tabs(self, make_item, sheet_name):
        item = make_item("/a.xlsx", workbook())
        options = ExcelByPandasOptions(sheet_name=sheet_name)  # None: all
        view = excel_view(Excel(), item, options, PANDAS_LIMITS)
        assert isinstance(view, TableSetView)
        assert sorted(leaf.id for leaf in view.leaves()) == ["one", "two"]
        assert view.loader("one").more

    def test_parquet_arguments_in_the_data_browser(self, make_item):
        item = make_item("/a.parquet", parquet_bytes({"a": [1, 2, 3], "b": [4, 5, 6]}))
        options = ParquetByPandasOptions(
            columns=["a"], filters=[("a", ">", 1)], dtype_backend="pyarrow"
        )
        query = parquet_view(Parquet(), item, options, LIMITS)
        assert query.data["a"].tolist() == [2, 3]
        assert list(query.data.columns) == ["a"]
        assert str(query.data["a"].dtype) == "int64[pyarrow]"
        code = parquet_as_data_frame(Parquet(), item, options)
        assert last_line(code) == (
            "df = pd.read_parquet('memory:///a.parquet', columns=['a'],"
            " dtype_backend='pyarrow', filters=[('a', '>', 1)])"
        )
