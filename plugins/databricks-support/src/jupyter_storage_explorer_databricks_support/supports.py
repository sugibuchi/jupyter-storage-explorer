"""Databricks Connect as an engine: the formats pyspark-support reads with
Spark, read on a Databricks cluster or serverless compute instead.

The supports are pyspark-support's, with sessions made by Databricks
Connect's ``DatabricksSession``. A file of fsspec-databricks' filesystem is
read on that filesystem's workspace, with its Databricks SDK configuration:
the storage shown and the compute are the same workspace's, with the same
credentials. Other files are read with Databricks Connect's own
configuration, e.g. the environment's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fsspec.implementations.dirfs import DirFileSystem
from jupyter_storage_explorer_pyspark_support import (
    CsvByPySpark,
    DeltaLakeByPySpark,
    JsonLinesByPySpark,
    ParquetByPySpark,
)

from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer_databricks_support.mapper import (
    DatabricksWorkspaceMapper,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fsspec import AbstractFileSystem
    from jupyter_storage_explorer_pyspark_support import PySparkOptions

    from jupyter_storage_explorer.formats.base import ItemContext


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
    builder = DatabricksConnect().load().DatabricksSession.builder
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


class _ByDatabricksConnect:
    """pyspark-support's support of a format, with Databricks Connect's
    sessions. Its options are those of the support, in ``engine_options``
    under this engine's key."""

    engine = DatabricksConnectEngine
    session_import = "from databricks.connect import DatabricksSession"

    def session(self, ctx: ItemContext, options: PySparkOptions) -> Any:
        return databricks_session(ctx.fs, options.session_options)

    def session_code(self, ctx: ItemContext, options: PySparkOptions) -> str:
        # The workspace of Databricks Connect's configuration: the code never
        # holds the explorer's credentials.
        config = options.code_value("session_options") or {}
        return "\n".join(
            [
                "spark = DatabricksSession.builder.getOrCreate()",
                *(
                    f"spark.conf.set({key!r}, {value!r})"
                    for key, value in config.items()
                ),
            ]
        )


class CsvByDatabricksConnect(_ByDatabricksConnect, CsvByPySpark):
    pass


class JsonLinesByDatabricksConnect(_ByDatabricksConnect, JsonLinesByPySpark):
    pass


class ParquetByDatabricksConnect(_ByDatabricksConnect, ParquetByPySpark):
    pass


class DeltaLakeByDatabricksConnect(_ByDatabricksConnect, DeltaLakeByPySpark):
    # Databricks has Delta Lake: delta-spark is for local sessions.
    additional_requirements = ()
