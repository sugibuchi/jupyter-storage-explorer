"""Databricks support for Storage Explorer.

A Databricks workspace's files, Unity Catalog volumes, workspace files and
legacy DBFS, through fsspec-databricks, with locations that name the
workspace. Experimental, as fsspec-databricks is.

The plugin, ``DatabricksSupport``, is found by explorers through its entry
point (``databricks-support``); its library is installed with the "full"
extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_databricks_support.mapper import (
    DatabricksLocation,
    DatabricksWorkspaceMapper,
)


class DatabricksSupport(StorageExplorerPlugin):
    key = "databricks-support"

    @property
    def filesystem_mappers(self):
        return (DatabricksWorkspaceMapper(),)


__all__ = [
    "DatabricksLocation",
    "DatabricksSupport",
    "DatabricksWorkspaceMapper",
]
