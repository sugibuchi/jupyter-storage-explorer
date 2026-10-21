"""The PySpark supports' views (formats/supports/pyspark.py), on sqlframe:
Spark's API on DuckDB (real Spark needs Java), as their Spark session."""

from __future__ import annotations

import polars as pl
import pytest
from items import local_item
from jupyter_storage_explorer_pyspark_support import (
    CsvByPySpark,
    JsonLinesByPySpark,
    ParquetByPySpark,
)
from jupyter_storage_explorer_pyspark_support import supports as pyspark
from sqlframe.duckdb import DuckDBSession

from jupyter_storage_explorer.formats import (
    Csv,
    JsonLines,
    Parquet,
    QueryView,
    SupportOptions,
    ViewLimits,
)

LIMITS = ViewLimits()


@pytest.fixture(autouse=True)
def session(monkeypatch):
    spark = DuckDBSession()
    monkeypatch.setattr(pyspark, "spark_session", lambda: spark)
    # DuckDB reads local paths, not file:// URLs, as Spark does.
    monkeypatch.setattr(pyspark, "_url", lambda ctx: ctx.library_url)
    return spark


def rows(view):
    assert isinstance(view, QueryView)
    return [tuple(row) for row in view.data.collect()]


def test_parquet(tmp_path):
    path = tmp_path / "a.parquet"
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(path)
    view = ParquetByPySpark().view(
        Parquet(), local_item(path), SupportOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,), (3,)]


def test_csv_with_its_separator(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("x;y\n1;2\n3;4\n")
    view = CsvByPySpark().view(Csv(), local_item(path), SupportOptions(), LIMITS)
    assert view.data.columns == ["x", "y"]
    assert rows(view) == [(1, 2), (3, 4)]


def test_json_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"i": 1}\n{"i": 2}\n')
    view = JsonLinesByPySpark().view(
        JsonLines(), local_item(path), SupportOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,)]
