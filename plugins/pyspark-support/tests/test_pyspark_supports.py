"""pyspark-support: its supports' views and options, on a local Spark session
(skipped without Java, or without pyspark, which the repository's shared
environment leaves out: CI runs them alone, with Java); their code; the
session's builder, faked; its engine and entry point."""

from __future__ import annotations

import concurrent.futures
import os
import shutil
from dataclasses import fields
from importlib.metadata import entry_points
from types import SimpleNamespace

import pytest
from jupyter_storage_explorer_pyspark_support import (
    CsvByPySpark,
    CsvByPySparkOptions,
    DeltaLakeByPySpark,
    DeltaLakeByPySparkOptions,
    JsonLinesByPySpark,
    JsonLinesByPySparkOptions,
    ParquetByPySpark,
    ParquetByPySparkOptions,
    PySpark,
    PySparkEngine,
    PySparkOptions,
    PySparkSupport,
    spark_url,
)
from jupyter_storage_explorer_pyspark_support import supports as pyspark

from jupyter_storage_explorer.filesystems import S3Location
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    JsonLines,
    Parquet,
    QueryView,
    ViewLimits,
)
from jupyter_storage_explorer.testing import local_item

LIMITS = ViewLimits()
# The real one: the session fixture below replaces it for the views.
SPARK_SESSION = pyspark.spark_session
FORMAT_OPTIONS = (
    CsvByPySparkOptions,
    JsonLinesByPySparkOptions,
    ParquetByPySparkOptions,
    DeltaLakeByPySparkOptions,
)


@pytest.fixture(scope="module")
def local_spark():
    """A local Spark session, for the views; skipped without pyspark or Java."""
    pytest.importorskip("pyspark")
    if shutil.which("java") is None and not os.environ.get("JAVA_HOME"):
        pytest.skip("Spark needs Java")
    from pyspark.sql import SparkSession  # noqa: PLC0415

    spark = (
        SparkSession.builder.master("local[1]")
        .appName("pyspark-support tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )
    yield spark
    spark.stop()


@pytest.fixture
def session(local_spark, monkeypatch):
    """The views' Spark session (``spark_session``): the local one, and the
    session options each view asked it with (``asked``)."""
    asked = []

    def spark_session(session_options=None):
        asked.append(session_options)
        return local_spark

    monkeypatch.setattr(pyspark, "spark_session", spark_session)
    return SimpleNamespace(spark=local_spark, asked=asked)


def parquet_file(session, path, rows, column):
    """A Parquet file of ``rows`` (one value each) at ``path``, written by
    Spark: it writes a folder, whose one part file is moved there. Skipped on
    Windows without Hadoop's winutils (``HADOOP_HOME``), which Spark needs
    there to write files, though not to read them."""
    if os.name == "nt" and not os.environ.get("HADOOP_HOME"):
        pytest.skip("Spark writes files on Windows only with HADOOP_HOME")
    folder = path.with_name(f"{path.name}.spark")
    df = session.spark.createDataFrame([(v,) for v in rows], [column])
    df.coalesce(1).write.parquet(str(folder))
    next(folder.glob("part-*.parquet")).rename(path)
    shutil.rmtree(folder)
    return path


def rows(view):
    assert isinstance(view, QueryView)
    return [tuple(row) for row in view.data.collect()]


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="pyspark-support"
    )
    plugin = entry_point.load()()
    assert isinstance(plugin, PySparkSupport)
    assert plugin.description == "PySpark support for Storage Explorer"
    assert CsvByPySpark in plugin.format_supports


def test_engine_not_with_databricks_connects_pyspark(monkeypatch):
    # Its pyspark makes no session with SparkSession.builder: databricks-
    # support's engine uses it instead.
    monkeypatch.setattr(pyspark._DatabricksConnect, "is_installed", lambda self: True)
    assert not PySpark().is_installed()
    assert not PySparkEngine.is_installed()
    assert [p.package for p in PySparkEngine.packages()] == ["pyspark"]


def test_spark_url(tmp_path):
    assert spark_url("s3://bucket/x") == "s3a://bucket/x"
    assert (
        spark_url("abfs://c@a.dfs.core.windows.net/x")
        == "abfss://c@a.dfs.core.windows.net/x"
    )
    assert spark_url("az://c/x") == "abfss://c/x"
    assert spark_url("gs://bucket/x") == "gs://bucket/x"
    # Databricks' form; "dbfs://Volumes" would name a host.
    assert spark_url("dbfs://Volumes/c/s/v/x") == "dbfs:/Volumes/c/s/v/x"
    assert spark_url("dbfs:/Volumes/c/s/v/x") == "dbfs:/Volumes/c/s/v/x"
    # Local files: Spark reads their file:/// URLs.
    assert spark_url(local_item(tmp_path).location.url).startswith("file:///")


def test_parquet(tmp_path, session):
    path = parquet_file(session, tmp_path / "a.parquet", [1, 2, 3], "a")
    view = ParquetByPySpark().view(
        Parquet(), local_item(path), ParquetByPySparkOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,), (3,)]


def test_csv_with_its_separator(tmp_path, session):
    path = tmp_path / "a.csv"
    path.write_text("x;y\n1;2\n3;4\n")
    view = CsvByPySpark().view(Csv(), local_item(path), CsvByPySparkOptions(), LIMITS)
    assert view.data.columns == ["x", "y"]
    assert rows(view) == [(1, 2), (3, 4)]


def test_viewed_in_a_worker_read_on_the_main_thread(tmp_path, session):
    # The explorer makes views in a worker thread, so that a session starting
    # leaves the kernel free, then reads their data in other threads.
    path = tmp_path / "a.csv"
    path.write_text("x\n1\n2\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
        view = worker.submit(
            CsvByPySpark().view, Csv(), local_item(path), CsvByPySparkOptions(), LIMITS
        ).result()
    assert rows(view) == [(1,), (2,)]


def test_json_lines(tmp_path, session):
    path = tmp_path / "a.jsonl"
    path.write_text('{"i": 1}\n{"i": 2}\n')
    view = JsonLinesByPySpark().view(
        JsonLines(), local_item(path), JsonLinesByPySparkOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,)]


class TestOptions:
    def test_reader_options_override_the_defaults(self, tmp_path, session):
        # No header: the reader option wins over the field's header=True.
        path = tmp_path / "a.csv"
        path.write_text("1;2\n3;4\n")
        options = CsvByPySparkOptions(reader_options={"header": False})
        view = CsvByPySpark().view(Csv(), local_item(path), options, LIMITS)
        assert rows(view) == [(1, 2), (3, 4)]

    def test_fields_reach_the_reader(self):
        # A reader recording its options, in the order given.
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
        path = parquet_file(session, tmp_path / "a.parquet", [1], "a")
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


class TestRecipes:
    def test_csv_with_its_separator(self, make_item):
        [code] = (
            CsvByPySpark()
            .recipe(Csv(), make_item("/a.tsv", b"x\ty\n"), CsvByPySparkOptions())
            .values()
        )
        assert code.splitlines()[-1] == (
            "df = spark.read.options(sep='\\t', header=True, inferSchema=True)"
            ".csv('memory:///a.tsv')"
        )

    def test_spark_session_created(self, make_item):
        [code] = (
            ParquetByPySpark()
            .recipe(Parquet(), make_item("/a.parquet", b""), ParquetByPySparkOptions())
            .values()
        )
        assert code == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.parquet('memory:///a.parquet')"
        )

    def test_partitioned_parquet(self, make_item, memfs):
        # Spark finds partitions itself.
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        [code] = (
            ParquetByPySpark()
            .recipe(Parquet(), make_item("/t"), ParquetByPySparkOptions())
            .values()
        )
        assert code.splitlines()[-1] == "df = spark.read.parquet('memory:///t')"

    def test_delta(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        [code] = (
            DeltaLakeByPySpark()
            .recipe(DeltaLake(), item, DeltaLakeByPySparkOptions())
            .values()
        )
        # The session is obtained, not configured: Delta Lake's setup in
        # Spark is left to the user. Spark's URL: s3a.
        assert code == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "# Needs Delta Lake in the Spark session (Databricks has it)\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.format(\"delta\").load('s3a://b/t')"
        )


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
    """spark_session(), with pyspark faked."""

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
