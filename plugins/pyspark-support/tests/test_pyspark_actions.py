"""pyspark-support: its actions' views and options, on a local Spark session
(skipped without Java, or without pyspark, which the repository's shared
environment leaves out: CI runs them alone, with Java); their code; the
session's builder, faked; its engine and entry point."""

from __future__ import annotations

import concurrent.futures
import importlib.metadata
import importlib.util
import os
import shutil
import sys
from dataclasses import fields
from types import SimpleNamespace

import narwhals as nw
import pytest
from jupyter_storage_explorer_pyspark_support import (
    PYSPARK_ACTIONS,
    CsvByPySparkOptions,
    DeltaLakeByPySparkOptions,
    JsonLinesByPySparkOptions,
    ParquetByPySparkOptions,
    PySpark,
    PySparkEngine,
    PySparkOptions,
    PySparkSupport,
    csv_as_data_frame,
    csv_view,
    delta_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
    spark_rows,
    spark_url,
)
from jupyter_storage_explorer_pyspark_support import actions as pyspark

from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer.actions import CodeAction
from jupyter_storage_explorer.filesystems.locations import S3Location
from jupyter_storage_explorer.formats import Csv, DeltaLake, JsonLines, Parquet
from jupyter_storage_explorer.testing import check_plugin, local_item
from jupyter_storage_explorer.views import QueryView, ViewLimits

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
    plugin = check_plugin("pyspark-support")
    assert isinstance(plugin, PySparkSupport)
    assert plugin.description == "PySpark support for Storage Explorer"
    assert plugin.actions == PYSPARK_ACTIONS
    assert csv_view in plugin.actions


def test_one_options_class_per_format():
    # A format's view and code take the same options.
    by_format: dict[type, set[type]] = {}
    for action in PYSPARK_ACTIONS:
        by_format.setdefault(action.format, set()).add(action.options_model)
    assert all(len(models) == 1 for models in by_format.values())


def test_engine_not_with_another_packages_pyspark(monkeypatch):
    # A pyspark module of another distribution, e.g. Databricks Connect's,
    # makes no session with SparkSession.builder.
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(importlib.metadata, "distribution", missing)
    assert not PySpark().is_installed()
    assert not PySparkEngine.is_installed()
    assert [p.package for p in PySparkEngine.requirements] == ["pyspark", "pyarrow"]


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
    view = parquet_view(Parquet(), local_item(path), ParquetByPySparkOptions(), LIMITS)
    assert rows(view) == [(1,), (2,), (3,)]


def test_csv_with_its_separator(tmp_path, session):
    path = tmp_path / "a.csv"
    path.write_text("x;y\n1;2\n3;4\n")
    view = csv_view(Csv(), local_item(path), CsvByPySparkOptions(), LIMITS)
    assert view.data.columns == ["x", "y"]
    assert rows(view) == [(1, 2), (3, 4)]


def test_viewed_in_a_worker_read_on_the_main_thread(tmp_path, session):
    # The explorer makes views in a worker thread, so that a session starting
    # leaves the kernel free, then reads their data in other threads.
    path = tmp_path / "a.csv"
    path.write_text("x\n1\n2\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
        view = worker.submit(
            csv_view, Csv(), local_item(path), CsvByPySparkOptions(), LIMITS
        ).result()
    assert rows(view) == [(1,), (2,)]


def test_rows_skipped_by_spark(tmp_path, session):
    # The data browser reads pages with Spark's offset, not all rows before.
    path = tmp_path / "a.csv"
    path.write_text("x\n1\n2\n3\n4\n5\n")
    view = csv_view(Csv(), local_item(path), CsvByPySparkOptions(), LIMITS)
    assert view.fetch is spark_rows
    page = spark_rows(nw.from_native(view.data), 2, 2)
    assert page["x"].to_list() == [3, 4]


def test_rows_left_to_the_default_without_offset():
    # A Spark before 3.4: its DataFrame has no offset method (its attributes
    # are also its columns, so the class is asked).
    class OldDataFrame:
        def __getattr__(self, name):
            return f"column {name}"

    lf = SimpleNamespace(to_native=OldDataFrame)
    assert spark_rows(lf, 5, 2) is None


def test_json_lines(tmp_path, session):
    path = tmp_path / "a.jsonl"
    path.write_text('{"i": 1}\n{"i": 2}\n')
    view = json_lines_view(
        JsonLines(), local_item(path), JsonLinesByPySparkOptions(), LIMITS
    )
    assert rows(view) == [(1,), (2,)]


class TestSupportedProtocols:
    """Spark reads the item's URL itself: only those of its protocols."""

    def supports(self, item, options=None, task="view"):
        options = options or ParquetByPySparkOptions()
        action = parquet_view if task == "view" else parquet_as_data_frame
        return action.does(Parquet(), item, options)

    def test_by_default(self, make_item, tmp_path):
        on_s3 = make_item("/a.parquet", b"", location=S3Location(bucket="b", key="a"))
        assert self.supports(on_s3)  # s3 read as s3a
        assert self.supports(local_item(tmp_path))
        # fsspec's memory filesystem: no view, no code.
        assert not self.supports(make_item("/a.parquet", b""))
        assert not self.supports(make_item("/a.parquet", b""), task="recipe")

    def test_given(self, make_item, tmp_path):
        options = ParquetByPySparkOptions(supported_protocols=["S3A"])
        on_s3 = make_item("/a.parquet", b"", location=S3Location(bucket="b", key="a"))
        assert self.supports(on_s3, options)  # whatever the case
        assert not self.supports(local_item(tmp_path), options)

    def test_any(self, make_item):
        options = ParquetByPySparkOptions(supported_protocols=None)
        assert self.supports(make_item("/a.parquet", b""), options)

    def test_not_a_reader_option(self):
        assert "supportedProtocols" not in PySparkOptions().format_options()
        assert ".option" not in pyspark.spark_reader_code(PySparkOptions())

    def test_by_engine_options(self, make_item, monkeypatch):
        monkeypatch.setattr(PySpark, "is_installed", lambda self: True)
        chain = ActionChain(
            [parquet_view, parquet_as_data_frame],
            {"pyspark": {"*": {"supported_protocols": None}}},
        )
        item = make_item("/a.parquet", b"")
        assert chain.of(Parquet(), item, CodeAction) == [parquet_as_data_frame]


class TestOptions:
    def test_reader_options_override_the_defaults(self, tmp_path, session):
        # No header: the reader option wins over the field's header=True.
        path = tmp_path / "a.csv"
        path.write_text("1;2\n3;4\n")
        options = CsvByPySparkOptions(reader_options={"header": False})
        view = csv_view(Csv(), local_item(path), options, LIMITS)
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
        pyspark.spark_reader(options, SimpleNamespace(read=Reader()), {"sep": ";"})
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
        parquet_view(Parquet(), local_item(path), options, LIMITS)
        assert session.asked == [{"spark.sql.shuffle.partitions": "4"}]

    def test_spark_names(self):
        options = CsvByPySparkOptions(
            null_value="NA", timestamp_ntz_format="yyyy", header=None
        )
        assert options.format_options() == {
            "inferSchema": True,
            "nullValue": "NA",
            "timestampNTZFormat": "yyyy",
        }
        assert PySparkOptions().format_options() == {}

    @pytest.mark.parametrize("model", FORMAT_OPTIONS)
    def test_options_left_to_spark_by_default(self, model):
        # engine_options set only some, so each has a default: None, which
        # leaves it to Spark, but CSV's header and inferSchema.
        assert len(fields(model)) > len(fields(PySparkOptions))
        expected = (
            {"header": True, "inferSchema": True}
            if model is CsvByPySparkOptions
            else {}
        )
        assert model().format_options() == expected

    def test_code(self, make_item):
        options = CsvByPySparkOptions(
            session_options={
                "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                # Credentials never appear in the code.
                "spark.hadoop.fs.azure.account.key.acct.dfs.core.windows.net": "s3cr3t",
            },
            reader_options={"mode": "DROPMALFORMED"},
        )
        code = csv_as_data_frame(Csv(), make_item("/a.csv", b"x,y\n"), options)
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
        code = csv_as_data_frame(Csv(), make_item("/a.csv", b"x;y\n"), options)
        # The separator given replaces the one detected.
        assert code.splitlines()[-1] == (
            "df = spark.read.options(sep='|', header=True, inferSchema=True,"
            " mode='FAILFAST').csv('memory:///a.csv')"
        )
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        delta_options = DeltaLakeByPySparkOptions(version_as_of=3)
        delta = delta_as_data_frame(DeltaLake(), make_item("/t"), delta_options)
        assert delta.splitlines()[-1] == (
            "df = spark.read.options(versionAsOf=3)"
            ".format(\"delta\").load('memory:///t')"
        )

    def test_code_without_the_options_overridden(self, make_item, memfs):
        options = CsvByPySparkOptions(reader_options={"header": False})
        code = csv_as_data_frame(Csv(), make_item("/a.csv", b"x,y\n"), options)
        assert code.splitlines()[-1] == (
            "df = spark.read.options(inferSchema=True).option('header', False)"
            ".csv('memory:///a.csv')"
        )
        # Spark's option names ignore case.
        parquet = ParquetByPySparkOptions(
            merge_schema=True, reader_options={"MERGESCHEMA": False}
        )
        assert pyspark.spark_reader_code(parquet) == ".option('MERGESCHEMA', False)"


class TestRecipes:
    def test_csv_with_its_separator(self, make_item):
        code = csv_as_data_frame(
            Csv(), make_item("/a.tsv", b"x\ty\n"), CsvByPySparkOptions()
        )
        assert code.splitlines()[-1] == (
            "df = spark.read.options(sep='\\t', header=True, inferSchema=True)"
            ".csv('memory:///a.tsv')"
        )

    def test_spark_session_created(self, make_item):
        code = parquet_as_data_frame(
            Parquet(), make_item("/a.parquet", b""), ParquetByPySparkOptions()
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
        code = parquet_as_data_frame(
            Parquet(), make_item("/t"), ParquetByPySparkOptions()
        )
        assert code.splitlines()[-1] == "df = spark.read.parquet('memory:///t')"

    def test_delta(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        code = delta_as_data_frame(DeltaLake(), item, DeltaLakeByPySparkOptions())
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
        # What spark_session imports: pyspark.sql's SparkSession.
        module = SimpleNamespace(SparkSession=SparkSession)
        monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace(sql=module))
        monkeypatch.setitem(sys.modules, "pyspark.sql", module)
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
