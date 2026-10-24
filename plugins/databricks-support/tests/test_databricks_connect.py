"""databricks-support: Databricks Connect as an engine, on a fake of
Databricks Connect (the real one needs Databricks compute): the session on
the workspace of fsspec-databricks' filesystem, and the code."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fsspec import AbstractFileSystem
from fsspec.implementations.dirfs import DirFileSystem
from jupyter_storage_explorer_databricks_support import (
    DATABRICKS_PROTOCOLS,
    CsvByDatabricksConnect,
    DatabricksConnect,
    DatabricksConnectEngine,
    DatabricksSupport,
    DeltaLakeByDatabricksConnect,
    JsonLinesByDatabricksConnect,
    ParquetByDatabricksConnect,
    databricks_session,
)
from jupyter_storage_explorer_pyspark_support import (
    ParquetByPySpark,
    ParquetByPySparkOptions,
)

from jupyter_storage_explorer.filesystems import S3Location
from jupyter_storage_explorer.formats import Parquet
from jupyter_storage_explorer.testing import local_item

CONFIG = SimpleNamespace(host="https://adb-1.azuredatabricks.net")


class DatabricksFileSystem(AbstractFileSystem):
    """As fsspec-databricks' (matched by its qualified name)."""

    cachable = False
    protocol = "dbfs"
    config = CONFIG


DatabricksFileSystem.__module__ = "fsspec_databricks.spec"


class Session:
    """A Spark session: its runtime configuration."""

    def __init__(self) -> None:
        self.conf = SimpleNamespace(
            set=lambda key, value: self.set.append((key, value))
        )
        self.set: list[tuple[str, str]] = []


@pytest.fixture
def connect(monkeypatch):
    """Databricks Connect, faked: the builder records the SDK configuration it
    is given (``sdk_config``), and ``getOrCreate`` gives ``session``."""
    state = SimpleNamespace(sdk_config=None, session=Session())

    class Builder:
        def sdkConfig(self, config):
            state.sdk_config = config
            return self

        def getOrCreate(self):
            return state.session

    module = SimpleNamespace(DatabricksSession=SimpleNamespace(builder=Builder()))
    monkeypatch.setattr(DatabricksConnect, "load", lambda self, sub=None: module)
    return state


class TestSession:
    def test_on_the_filesystems_workspace(self, connect):
        session = databricks_session(DatabricksFileSystem(), {"a.b": "1"})
        assert session is connect.session
        assert connect.sdk_config is CONFIG
        # Databricks Connect's builder takes no configuration: set at run time.
        assert session.set == [("a.b", "1")]

    def test_within_a_dirfilesystem(self, connect):
        fs = DirFileSystem("/Volumes/main", fs=DatabricksFileSystem())
        databricks_session(fs)
        assert connect.sdk_config is CONFIG

    def test_other_storages_with_its_own_configuration(self, connect, memfs):
        assert databricks_session(memfs) is connect.session
        assert connect.sdk_config is None

    def test_the_views_session(self, connect, make_item):
        item = make_item("/a.parquet", b"")
        options = ParquetByPySparkOptions(session_options={"a.b": "1"})
        assert ParquetByDatabricksConnect().session(item, options) is connect.session
        assert connect.session.set == [("a.b", "1")]


class TestCode:
    def test_the_session_by_databricks_connect(self, make_item):
        options = ParquetByPySparkOptions(
            session_options={
                "spark.sql.ansi.enabled": "true",
                # Credentials never appear in the code.
                "spark.hadoop.fs.azure.account.key.a.dfs.core.windows.net": "s3cr3t",
            }
        )
        [code] = (
            ParquetByDatabricksConnect()
            .recipe(Parquet(), make_item("/a.parquet", b""), options)
            .values()
        )
        assert code == (
            "from databricks.connect import DatabricksSession\n"
            "\n"
            "spark = DatabricksSession.builder.getOrCreate()\n"
            "spark.conf.set('spark.sql.ansi.enabled', 'true')\n"
            "df = spark.read.parquet('memory:///a.parquet')"
        )

    def test_pysparks_unchanged(self, make_item):
        [code] = (
            ParquetByPySpark()
            .recipe(Parquet(), make_item("/a.parquet", b""), ParquetByPySparkOptions())
            .values()
        )
        assert code.startswith("from pyspark.sql import SparkSession\n")


def test_the_engine():
    supports = DatabricksSupport().format_supports
    assert set(supports) == {
        CsvByDatabricksConnect,
        DeltaLakeByDatabricksConnect,
        JsonLinesByDatabricksConnect,
        ParquetByDatabricksConnect,
    }
    for support in supports:
        assert support.engine is DatabricksConnectEngine
    assert DatabricksConnectEngine.key == "databricks-connect"
    assert [p.package for p in DatabricksConnectEngine.packages()] == [
        "databricks-connect"
    ]
    # Databricks has Delta Lake: no delta-spark.
    assert DeltaLakeByDatabricksConnect.additional_requirements == ()


class TestSupportedProtocols:
    """The cluster reads the item's URL: not the kernel's local files."""

    def test_databricks_default(self, make_item, tmp_path):
        support = ParquetByDatabricksConnect()
        options = support.options_model()
        assert options.supported_protocols == DATABRICKS_PROTOCOLS
        on_s3 = make_item("/a.parquet", b"", location=S3Location(bucket="b", key="a"))
        assert support.supports(Parquet(), on_s3, options, "view")
        assert not support.supports(Parquet(), local_item(tmp_path), options, "view")
        # pyspark-support's own default still takes local files.
        assert ParquetByPySpark().supports(
            Parquet(), local_item(tmp_path), ParquetByPySparkOptions(), "view"
        )

    @pytest.mark.parametrize(
        "support",
        [
            CsvByDatabricksConnect,
            JsonLinesByDatabricksConnect,
            ParquetByDatabricksConnect,
            DeltaLakeByDatabricksConnect,
        ],
    )
    def test_every_format(self, support):
        assert "file" not in support.options_model().supported_protocols
