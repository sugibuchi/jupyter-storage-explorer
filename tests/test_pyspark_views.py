"""The PySpark supports' views and options (plugins/pyspark-support), on
sqlframe: Spark's API on DuckDB (real Spark needs Java), as their Spark
session; and the session's builder, faked."""

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import polars as pl
import pytest
from items import local_item
from jupyter_storage_explorer_pyspark_support import (
    CsvByPySpark,
    CsvByPySparkOptions,
    DeltaLakeByPySpark,
    DeltaLakeByPySparkOptions,
    JsonLinesByPySpark,
    JsonLinesByPySparkOptions,
    ParquetByPySpark,
    ParquetByPySparkOptions,
    PySparkOptions,
)
from jupyter_storage_explorer_pyspark_support import supports as pyspark
from sqlframe.duckdb import DuckDBSession

from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    JsonLines,
    Parquet,
    QueryView,
    ViewLimits,
)
from jupyter_storage_explorer.formats.packages import DatabricksConnect, PySpark

LIMITS = ViewLimits()
# The real one: the autouse fixture below replaces it for the views.
SPARK_SESSION = pyspark.spark_session
FORMAT_OPTIONS = (
    CsvByPySparkOptions,
    JsonLinesByPySparkOptions,
    ParquetByPySparkOptions,
    DeltaLakeByPySparkOptions,
)


@pytest.fixture(autouse=True)
def session(monkeypatch):
    spark = DuckDBSession()
    sessions = []

    def spark_session(session_options=None):
        sessions.append(session_options)
        return spark

    monkeypatch.setattr(pyspark, "spark_session", spark_session)
    # DuckDB reads local paths, not file:// URLs, as Spark does.
    monkeypatch.setattr(pyspark, "_url", lambda ctx: ctx.library_url)
    spark.asked = sessions  # the session options each view asked with
    return spark


def rows(view):
    assert isinstance(view, QueryView)
    return [tuple(row) for row in view.data.collect()]


def test_parquet(tmp_path):
    path = tmp_path / "a.parquet"
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(path)
    view = ParquetByPySpark().view(
        Parquet(), local_item(path), ParquetByPySparkOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,), (3,)]


def test_csv_with_its_separator(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("x;y\n1;2\n3;4\n")
    view = CsvByPySpark().view(Csv(), local_item(path), CsvByPySparkOptions(), LIMITS)
    assert view.data.columns == ["x", "y"]
    assert rows(view) == [(1, 2), (3, 4)]


def test_json_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"i": 1}\n{"i": 2}\n')
    view = JsonLinesByPySpark().view(
        JsonLines(), local_item(path), JsonLinesByPySparkOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,)]


class TestOptions:
    def test_reader_options_override_the_defaults(self, tmp_path):
        # No header: the reader option wins over the field's header=True.
        path = tmp_path / "a.csv"
        path.write_text("1;2\n3;4\n")
        options = CsvByPySparkOptions(reader_options={"header": False})
        view = CsvByPySpark().view(Csv(), local_item(path), options, LIMITS)
        assert rows(view) == [(1, 2), (3, 4)]

    def test_fields_reach_the_reader(self):
        # A reader recording its options: DuckDB's (sqlframe) takes few of
        # Spark's.
        given = []

        class Reader:
            def option(self, key, value):
                given.append((key, value))
                return self

        options = CsvByPySparkOptions(
            null_value="NA", reader_options={"nullvalue": "-"}
        )
        options.reader(SimpleNamespace(read=Reader()), {"sep": ";"})
        # The defaults, the fields, then the reader options, which override
        # them whatever their case.
        assert given == [
            ("sep", ";"),
            ("header", True),
            ("inferSchema", True),
            ("nullvalue", "-"),
        ]

    def test_session_options_reach_the_session(self, tmp_path, session):
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1]}).write_parquet(path)
        options = ParquetByPySparkOptions(
            session_options={"spark.sql.shuffle.partitions": "4"}
        )
        ParquetByPySpark().view(Parquet(), local_item(path), options, LIMITS)
        assert session.asked == [{"spark.sql.shuffle.partitions": "4"}]

    def test_spark_names(self):
        options = CsvByPySparkOptions(
            null_value="NA", timestamp_ntz_format="yyyy", header=None
        )
        assert options.spark_options() == {
            "inferSchema": True,
            "nullValue": "NA",
            "timestampNTZFormat": "yyyy",
        }
        assert PySparkOptions().spark_options() == {}

    @pytest.mark.parametrize("model", FORMAT_OPTIONS)
    def test_options_left_to_spark_by_default(self, model):
        # format_options set only some, so each has a default: None, which
        # leaves it to Spark, but CSV's header and inferSchema.
        assert len(fields(model)) > len(fields(PySparkOptions))
        expected = (
            {"header": True, "inferSchema": True}
            if model is CsvByPySparkOptions
            else {}
        )
        assert model().spark_options() == expected

    def test_code(self, make_item):
        options = CsvByPySparkOptions(
            session_options={
                "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                # Credentials never appear in the code.
                "spark.hadoop.fs.azure.account.key.acct.dfs.core.windows.net": "s3cr3t",
            },
            reader_options={"mode": "DROPMALFORMED"},
        )
        [code] = (
            CsvByPySpark()
            .recipe(Csv(), make_item("/a.csv", b"x,y\n"), options)
            .values()
        )
        assert code.splitlines()[2:] == [
            "spark = (",
            "    SparkSession.builder",
            "    .config('spark.sql.extensions', 'io.delta.sql.DeltaSparkSessionExtension')",
            "    .getOrCreate()",
            ")",
            "df = spark.read.options(header=True, inferSchema=True)"
            ".option('mode', 'DROPMALFORMED').csv('memory:///a.csv')",
        ]
        assert "s3cr3t" not in code

    def test_code_with_fields(self, make_item, memfs):
        options = CsvByPySparkOptions(sep="|", mode="FAILFAST")
        [code] = (
            CsvByPySpark()
            .recipe(Csv(), make_item("/a.csv", b"x;y\n"), options)
            .values()
        )
        # The separator given replaces the one detected.
        assert code.splitlines()[-1] == (
            "df = spark.read.options(sep='|', header=True, inferSchema=True,"
            " mode='FAILFAST').csv('memory:///a.csv')"
        )
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        delta_options = DeltaLakeByPySparkOptions(version_as_of=3)
        [delta] = (
            DeltaLakeByPySpark()
            .recipe(DeltaLake(), make_item("/t"), delta_options)
            .values()
        )
        assert delta.splitlines()[-1] == (
            "df = spark.read.options(versionAsOf=3)"
            ".format(\"delta\").load('memory:///t')"
        )

    def test_code_without_the_options_overridden(self, make_item, memfs):
        options = CsvByPySparkOptions(reader_options={"header": False})
        [code] = (
            CsvByPySpark()
            .recipe(Csv(), make_item("/a.csv", b"x,y\n"), options)
            .values()
        )
        assert code.splitlines()[-1] == (
            "df = spark.read.options(inferSchema=True).option('header', False)"
            ".csv('memory:///a.csv')"
        )
        # Spark's option names ignore case.
        parquet = ParquetByPySparkOptions(
            merge_schema=True, reader_options={"MERGESCHEMA": False}
        )
        assert parquet.reader_code() == ".option('MERGESCHEMA', False)"


class Builder:
    """A stand-in for SparkSession.builder: the configuration it is given."""

    def __init__(self, session):
        self.session = session
        self.config_given = {}

    def config(self, key, value):
        self.config_given[key] = value
        return self

    def getOrCreate(self):
        return self.session


class TestSession:
    """spark_session(), with pyspark (and Databricks Connect) faked."""

    @pytest.fixture
    def spark(self, monkeypatch):
        state = SimpleNamespace(active=None, created=object())
        builder = Builder(state.created)

        class SparkSession:
            getActiveSession = staticmethod(lambda: state.active)

        SparkSession.builder = builder
        monkeypatch.setattr(
            PySpark,
            "load",
            lambda self, sub=None: SimpleNamespace(SparkSession=SparkSession),
        )
        monkeypatch.setattr(DatabricksConnect, "is_installed", lambda self: False)
        state.builder = builder
        return state

    def test_created_with_the_options(self, spark):
        session = SPARK_SESSION({"spark.sql.shuffle.partitions": "4"})
        assert session is spark.created
        assert spark.builder.config_given == {"spark.sql.shuffle.partitions": "4"}

    def test_the_active_one(self, spark):
        spark.active = object()
        assert SPARK_SESSION() is spark.active
        assert spark.builder.config_given == {}  # not asked for a builder
