"""pandas-support: its supports' views (pandas reads through the item's
fsspec filesystem, eagerly: the first max_memory_rows rows) and code, and its
entry point."""

from __future__ import annotations

import io
import json
from importlib.metadata import entry_points

import pandas as pd
from jupyter_storage_explorer_pandas_support import (
    CsvByPandas,
    ExcelByPandas,
    JsonLinesByPandas,
    PandasOptions,
    PandasSupport,
    ParquetByPandas,
)

from jupyter_storage_explorer.formats import (
    Csv,
    Excel,
    JsonLines,
    Parquet,
    QueryView,
    ViewLimits,
)

LIMITS = ViewLimits(max_display_rows=2)
# pandas reads at most max_memory_rows rows.
PANDAS_LIMITS = ViewLimits(max_memory_rows=2)


def parquet_bytes(columns: dict) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(columns).to_parquet(buffer, index=False)
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
    assert CsvByPandas in plugin.format_supports


class TestViews:
    def test_csv(self, make_item):
        item = make_item("/a.csv", b"x;y\n1;2\n3;4\n5;6\n")
        query = CsvByPandas().view(Csv(), item, PandasOptions(), PANDAS_LIMITS)
        assert isinstance(query, QueryView)
        assert list(query.data.columns) == ["x", "y"]  # the separator detected
        assert query.data.values.tolist() == [[1, 2], [3, 4]]
        assert query.more

    def test_json_lines(self, make_item):
        lines = b"".join(json.dumps({"i": i}).encode() + b"\n" for i in range(5))
        item = make_item("/a.jsonl", lines)
        query = JsonLinesByPandas().view(
            JsonLines(), item, PandasOptions(), PANDAS_LIMITS
        )
        assert query.data["i"].tolist() == [0, 1]
        assert query.more

    def test_parquet_file(self, make_item):
        # pyarrow reads through the item's fsspec filesystem, so memory:// works.
        item = make_item("/a.parquet", parquet_bytes({"a": [1, 2, 3]}))
        query = ParquetByPandas().view(Parquet(), item, PandasOptions(), PANDAS_LIMITS)
        assert query.data["a"].tolist() == [1, 2]
        assert query.more
        whole = ParquetByPandas().view(Parquet(), item, PandasOptions(), LIMITS)
        assert (whole.data["a"].tolist(), whole.more) == ([1, 2, 3], False)

    def test_partitioned_parquet(self, make_item, memfs):
        for year in (2025, 2026):
            data = parquet_bytes({"a": [year, year]})
            memfs.pipe_file(f"/t/year={year}/part-0.parquet", data)
        fmt = Parquet()
        item = make_item("/t")
        assert fmt.matches(item)
        query = ParquetByPandas().view(fmt, item, PandasOptions(), LIMITS)
        # Every partition, its column from the folders' names.
        assert list(query.data.columns) == ["a", "year"]
        assert query.data["year"].astype(int).tolist() == [2025, 2025, 2026, 2026]

    def test_excel(self, make_item):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1, 2, 3]}).to_excel(
                writer, sheet_name="one", index=False
            )
            pd.DataFrame({"b": [1]}).to_excel(writer, sheet_name="two", index=False)
        item = make_item("/a.xlsx", buffer.getvalue())
        # The first sheet.
        query = ExcelByPandas().view(Excel(), item, PandasOptions(), PANDAS_LIMITS)
        assert (query.data["a"].tolist(), query.more) == ([1, 2], True)


class TestRecipes:
    def test_csv(self, make_item):
        [code] = (
            CsvByPandas()
            .recipe(Csv(), make_item("/a.tsv", b"x\ty\n"), PandasOptions())
            .values()
        )
        assert code.startswith("import pandas as pd")
        assert last_line(code) == "df = pd.read_csv('memory:///a.tsv', sep='\\t')"

    def test_partitioned_parquet(self, make_item, memfs):
        # pyarrow finds partitions itself.
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        [code] = (
            ParquetByPandas()
            .recipe(Parquet(), make_item("/t"), PandasOptions())
            .values()
        )
        assert last_line(code) == "df = pd.read_parquet('memory:///t')"

    def test_storage_options_without_secrets(self, make_item):
        options = PandasOptions(storage_options={"account_key": "k", "anon": True})
        [code] = (
            CsvByPandas().recipe(Csv(), make_item("/a.csv", b"a\n"), options).values()
        )
        assert last_line(code) == (
            "df = pd.read_csv('memory:///a.csv', storage_options={'anon': True})"
        )
