"""Databricks Connect as an engine: the formats pyspark-support reads with
Spark, read on a Databricks cluster or serverless compute instead, as
actions registered in order in ``DATABRICKS_ACTIONS``.

The actions are pyspark-support's, with sessions made by Databricks
Connect's ``DatabricksSession`` (``DATABRICKS_SESSIONS``). A file of
fsspec-databricks' filesystem is read on that filesystem's workspace, with
its Databricks SDK configuration: the storage shown and the compute are the
same workspace's, with the same credentials. Other files are read with
Databricks Connect's own configuration, e.g. the environment's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fsspec.implementations.dirfs import DirFileSystem
from jupyter_storage_explorer_pyspark_support import (
    CsvByPySparkOptions,
    DeltaLakeByPySparkOptions,
    JsonLinesByPySparkOptions,
    ParquetByPySparkOptions,
    PySparkOptions,
    SparkSessions,
    spark_can_read,
    spark_csv_code,
    spark_csv_view,
    spark_delta_code,
    spark_delta_view,
    spark_json_lines_code,
    spark_json_lines_view,
    spark_parquet_code,
    spark_parquet_view,
)
from jupyter_storage_explorer_pyspark_support.actions import AS_DATA_FRAME

from jupyter_storage_explorer.formats.actions import code, register_actions, view
from jupyter_storage_explorer.formats.base import ItemContext
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.packages import PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.views import View, ViewLimits
from jupyter_storage_explorer_databricks_support.mapper import (
    DatabricksWorkspaceMapper,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from fsspec import AbstractFileSystem


class DatabricksConnect(PythonPackage):
    """Spark sessions on Databricks compute, with PySpark's API: it brings a
    pyspark of its own, and replaces pyspark itself."""

    package = "databricks-connect"
    # "databricks" alone is a namespace other packages share (databricks-sdk).
    import_name = "databricks.connect"


class DatabricksConnectEngine(Engine):
    """Spark's Python API, on Databricks compute through Databricks Connect."""

    key = "databricks-connect"
    label = "Databricks Connect"
    requirements = (DatabricksConnect(),)


def databricks_session(
    fs: AbstractFileSystem | None = None,
    session_options: Mapping[str, Any] | None = None,
) -> Any:
    """A Databricks Connect session: on the workspace of ``fs``, if it is
    fsspec-databricks' filesystem, else with Databricks Connect's own
    configuration. ``getOrCreate`` returns the session already made with the
    same configuration, if any: in a Databricks notebook, its own.

    ``session_options`` are set as the session's runtime configuration
    (``spark.conf.set``): Databricks Connect's builder takes none."""
    from databricks.connect import DatabricksSession

    builder = DatabricksSession.builder
    if (config := _workspace_config(fs)) is not None:
        builder = builder.sdkConfig(config)
    session = builder.getOrCreate()
    for key, value in (session_options or {}).items():
        session.conf.set(key, value)
    return session


def _workspace_config(fs: AbstractFileSystem | None) -> Any:
    """The Databricks SDK configuration of ``fs``, if it is fsspec-databricks'
    filesystem (also within a ``DirFileSystem``); else None."""
    while isinstance(fs, DirFileSystem):
        fs = fs.fs
    if fs is None or not DatabricksWorkspaceMapper().matches(fs):
        return None
    return fs.config


def _session(ctx: ItemContext, options: PySparkOptions) -> Any:
    return databricks_session(ctx.fs, options.session_options)


def _session_code(ctx: ItemContext, options: PySparkOptions) -> str:
    # The workspace of Databricks Connect's configuration: the code never
    # holds the explorer's credentials.
    config = options.code_value("session_options") or {}
    return "\n".join(
        [
            "spark = DatabricksSession.builder.getOrCreate()",
            *(f"spark.conf.set({key!r}, {value!r})" for key, value in config.items()),
        ]
    )


# The actions' sessions: Databricks Connect's. Their options are those of
# pyspark-support's actions, in ``engine_options`` under this engine's key.
DATABRICKS_SESSIONS = SparkSessions(
    session=_session,
    code_import="from databricks.connect import DatabricksSession",
    code=_session_code,
)


# The URL schemes Spark reads on Databricks compute by default, as Spark names
# them: the workspace's files (dbfs) and cloud storage. Not the kernel's local
# files, which the cluster does not see, nor HDFS. pyspark-support's
# ``supported_protocols``, with this default.
DATABRICKS_PROTOCOLS = ("dbfs", "s3a", "abfss", "abfs", "wasbs", "wasb", "gs")


@dataclass(frozen=True, kw_only=True)
class CsvByDatabricksConnectOptions(CsvByPySparkOptions):
    supported_protocols: Sequence[str] | None = DATABRICKS_PROTOCOLS


@dataclass(frozen=True, kw_only=True)
class JsonLinesByDatabricksConnectOptions(JsonLinesByPySparkOptions):
    supported_protocols: Sequence[str] | None = DATABRICKS_PROTOCOLS


@dataclass(frozen=True, kw_only=True)
class ParquetByDatabricksConnectOptions(ParquetByPySparkOptions):
    supported_protocols: Sequence[str] | None = DATABRICKS_PROTOCOLS


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByDatabricksConnectOptions(DeltaLakeByPySparkOptions):
    supported_protocols: Sequence[str] | None = DATABRICKS_PROTOCOLS


# Delta Lake: Databricks has it, so no delta-spark, which is for local
# sessions.


@code(
    format=DeltaLake,
    engine=DatabricksConnectEngine,
    label=AS_DATA_FRAME,
    check=spark_can_read,
)
def delta_as_data_frame(
    fmt: DeltaLake, ctx: ItemContext, options: DeltaLakeByDatabricksConnectOptions
) -> str:
    """A Delta Lake table into a DataFrame."""
    return spark_delta_code(DATABRICKS_SESSIONS, ctx, options)


@view(
    format=DeltaLake,
    engine=DatabricksConnectEngine,
    check=spark_can_read,
    code=delta_as_data_frame,
)
def delta_view(
    fmt: DeltaLake,
    ctx: ItemContext,
    options: DeltaLakeByDatabricksConnectOptions,
    limits: ViewLimits,
) -> View:
    """A Delta Lake table in the data browser."""
    return spark_delta_view(DATABRICKS_SESSIONS, ctx, options)


@code(
    format=Parquet,
    engine=DatabricksConnectEngine,
    label=AS_DATA_FRAME,
    check=spark_can_read,
)
def parquet_as_data_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDatabricksConnectOptions
) -> str:
    """A Parquet file or a folder of them into a DataFrame."""
    return spark_parquet_code(DATABRICKS_SESSIONS, ctx, options)


@view(
    format=Parquet,
    engine=DatabricksConnectEngine,
    check=spark_can_read,
    code=parquet_as_data_frame,
)
def parquet_view(
    fmt: Parquet,
    ctx: ItemContext,
    options: ParquetByDatabricksConnectOptions,
    limits: ViewLimits,
) -> View:
    """A Parquet file or a folder of them in the data browser."""
    return spark_parquet_view(DATABRICKS_SESSIONS, ctx, options)


@code(
    format=Csv,
    engine=DatabricksConnectEngine,
    label=AS_DATA_FRAME,
    check=spark_can_read,
)
def csv_as_data_frame(
    fmt: Csv, ctx: ItemContext, options: CsvByDatabricksConnectOptions
) -> str:
    """CSV into a DataFrame."""
    return spark_csv_code(DATABRICKS_SESSIONS, fmt, ctx, options)


@view(
    format=Csv,
    engine=DatabricksConnectEngine,
    check=spark_can_read,
    code=csv_as_data_frame,
)
def csv_view(
    fmt: Csv,
    ctx: ItemContext,
    options: CsvByDatabricksConnectOptions,
    limits: ViewLimits,
) -> View:
    """CSV in the data browser."""
    return spark_csv_view(DATABRICKS_SESSIONS, fmt, ctx, options, limits)


@code(
    format=JsonLines,
    engine=DatabricksConnectEngine,
    label=AS_DATA_FRAME,
    check=spark_can_read,
)
def json_lines_as_data_frame(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByDatabricksConnectOptions
) -> str:
    """JSON Lines into a DataFrame."""
    return spark_json_lines_code(DATABRICKS_SESSIONS, ctx, options)


@view(
    format=JsonLines,
    engine=DatabricksConnectEngine,
    check=spark_can_read,
    code=json_lines_as_data_frame,
)
def json_lines_view(
    fmt: JsonLines,
    ctx: ItemContext,
    options: JsonLinesByDatabricksConnectOptions,
    limits: ViewLimits,
) -> View:
    """JSON Lines in the data browser."""
    return spark_json_lines_view(DATABRICKS_SESSIONS, ctx, options)


# In the order tried.
DATABRICKS_ACTIONS = register_actions(
    delta_view,
    delta_as_data_frame,
    parquet_view,
    parquet_as_data_frame,
    csv_view,
    csv_as_data_frame,
    json_lines_view,
    json_lines_as_data_frame,
)
