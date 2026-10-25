"""Databricks support for Storage Explorer.

A Databricks workspace's files, Unity Catalog volumes, workspace files and
legacy DBFS, through fsspec-databricks, with locations that name the
workspace; and Databricks Connect as an engine, reading the formats
pyspark-support reads on Databricks compute. Experimental, as
fsspec-databricks is.

The plugin, ``DatabricksSupport``, is found by explorers through its entry
point (``databricks-support``); its libraries are installed with the "full"
extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_databricks_support.actions import (
    DATABRICKS_ACTIONS,
    DATABRICKS_PROTOCOLS,
    DATABRICKS_SESSIONS,
    CsvByDatabricksConnectOptions,
    DatabricksConnect,
    DatabricksConnectEngine,
    DeltaLakeByDatabricksConnectOptions,
    JsonLinesByDatabricksConnectOptions,
    ParquetByDatabricksConnectOptions,
    csv_as_data_frame,
    csv_view,
    databricks_session,
    delta_as_data_frame,
    delta_view,
    json_lines_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
)
from jupyter_storage_explorer_databricks_support.mapper import (
    DatabricksLocation,
    DatabricksWorkspaceMapper,
)


class DatabricksSupport(StorageExplorerPlugin):
    key = "databricks-support"

    @property
    def filesystem_mappers(self):
        return (DatabricksWorkspaceMapper(),)

    @property
    def actions(self):
        return DATABRICKS_ACTIONS


__all__ = [
    "DATABRICKS_ACTIONS",
    "DATABRICKS_PROTOCOLS",
    "DATABRICKS_SESSIONS",
    "CsvByDatabricksConnectOptions",
    "DatabricksConnect",
    "DatabricksConnectEngine",
    "DatabricksLocation",
    "DatabricksSupport",
    "DatabricksWorkspaceMapper",
    "DeltaLakeByDatabricksConnectOptions",
    "JsonLinesByDatabricksConnectOptions",
    "ParquetByDatabricksConnectOptions",
    "csv_as_data_frame",
    "csv_view",
    "databricks_session",
    "delta_as_data_frame",
    "delta_view",
    "json_lines_as_data_frame",
    "json_lines_view",
    "parquet_as_data_frame",
    "parquet_view",
]
