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
from jupyter_storage_explorer_databricks_support.mapper import (
    DatabricksLocation,
    DatabricksWorkspaceMapper,
)
from jupyter_storage_explorer_databricks_support.supports import (
    CsvByDatabricksConnect,
    DatabricksConnect,
    DatabricksConnectEngine,
    DeltaLakeByDatabricksConnect,
    JsonLinesByDatabricksConnect,
    ParquetByDatabricksConnect,
    databricks_session,
)


class DatabricksSupport(StorageExplorerPlugin):
    key = "databricks-support"

    @property
    def filesystem_mappers(self):
        return (DatabricksWorkspaceMapper(),)

    @property
    def format_supports(self):
        return (
            DeltaLakeByDatabricksConnect,
            ParquetByDatabricksConnect,
            CsvByDatabricksConnect,
            JsonLinesByDatabricksConnect,
        )


__all__ = [
    "CsvByDatabricksConnect",
    "DatabricksConnect",
    "DatabricksConnectEngine",
    "DatabricksLocation",
    "DatabricksSupport",
    "DatabricksWorkspaceMapper",
    "DeltaLakeByDatabricksConnect",
    "JsonLinesByDatabricksConnect",
    "ParquetByDatabricksConnect",
    "databricks_session",
]
