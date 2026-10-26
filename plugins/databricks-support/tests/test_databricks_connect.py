"""databricks-support: Databricks Connect as an engine, on a fake of
Databricks Connect (the real one needs Databricks compute): the session on
the workspace of fsspec-databricks' filesystem, and the code."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fsspec import AbstractFileSystem
from fsspec.implementations.dirfs import DirFileSystem
from jupyter_storage_explorer_databricks_support import (
    DATABRICKS_ACTIONS,
    DATABRICKS_PROTOCOLS,
    DATABRICKS_SESSIONS,
    DatabricksConnectEngine,
    DatabricksSupport,
    databricks_session,
    delta_as_data_frame,
    delta_view,
    parquet_as_data_frame,
    parquet_view,
)
from jupyter_storage_explorer_pyspark_support import ParquetByPySparkOptions
from jupyter_storage_explorer_pyspark_support import (
    parquet_as_data_frame as parquet_by_pyspark,
)
from jupyter_storage_explorer_pyspark_support import parquet_view as pyspark_view

from jupyter_storage_explorer.filesystems.locations import S3Location
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

    # What databricks_session imports: databricks.connect's DatabricksSession.
    module = SimpleNamespace(DatabricksSession=SimpleNamespace(builder=Builder()))
    monkeypatch.setitem(sys.modules, "databricks", SimpleNamespace(connect=module))
    monkeypatch.setitem(sys.modules, "databricks.connect", module)
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
        assert DATABRICKS_SESSIONS.session(item, options) is connect.session
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
        code = parquet_as_data_frame(Parquet(), make_item("/a.parquet", b""), options)
        assert code == (
            "from databricks.connect import DatabricksSession\n"
            "\n"
            "spark = DatabricksSession.builder.getOrCreate()\n"
            "spark.conf.set('spark.sql.ansi.enabled', 'true')\n"
            "df = spark.read.parquet('memory:///a.parquet')"
        )

    def test_pysparks_unchanged(self, make_item):
        item = make_item("/a.parquet", b"")
        code = parquet_by_pyspark(Parquet(), item, ParquetByPySparkOptions())
        assert code.startswith("from pyspark.sql import SparkSession\n")


def test_the_engine():
    actions = DatabricksSupport().actions
    assert actions == DATABRICKS_ACTIONS
    assert {a.format.name for a in actions} == {"csv", "delta", "json-lines", "parquet"}
    for action in actions:
        assert action.engine is DatabricksConnectEngine
    assert DatabricksConnectEngine.key == "databricks-connect"
    assert [p.package for p in DatabricksConnectEngine.requirements] == [
        "databricks-connect"
    ]
    # Databricks has Delta Lake: no delta-spark.
    assert delta_view.requires == delta_as_data_frame.requires == ()


def test_one_options_class_per_format():
    # A format's view and code take the same options.
    by_format: dict[type, set[type]] = {}
    for action in DATABRICKS_ACTIONS:
        by_format.setdefault(action.format, set()).add(action.options_model)
    assert all(len(models) == 1 for models in by_format.values())


class TestSupportedProtocols:
    """The cluster reads the item's URL: not the kernel's local files."""

    def test_databricks_default(self, make_item, tmp_path):
        options = parquet_view.options_model()
        assert options.supported_protocols == DATABRICKS_PROTOCOLS
        on_s3 = make_item("/a.parquet", b"", location=S3Location(bucket="b", key="a"))
        assert parquet_view.does(Parquet(), on_s3, options)
        assert not parquet_view.does(Parquet(), local_item(tmp_path), options)
        # pyspark-support's own default still takes local files.
        assert pyspark_view.does(
            Parquet(), local_item(tmp_path), ParquetByPySparkOptions()
        )

    @pytest.mark.parametrize("action", DATABRICKS_ACTIONS)
    def test_every_format(self, action):
        assert "file" not in action.options_model().supported_protocols
