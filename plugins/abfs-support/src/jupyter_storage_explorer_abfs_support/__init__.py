"""Azure Data Lake Storage support for Storage Explorer.

Azure Data Lake Storage Gen2: folders moved in one step, copies within an account on the server, empty folders.

The plugin, ``AbfsSupport``, is found by explorers through its entry point
(``abfs-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_abfs_support.operations import (
    AzureDataLakeGen2Operation,
)


class AbfsSupport(StorageExplorerPlugin):
    key = "abfs-support"
    label = "Azure Data Lake Storage support for Storage Explorer"
    filesystem_operations = (AzureDataLakeGen2Operation,)


__all__ = [
    "AbfsSupport",
    "AzureDataLakeGen2Operation",
]
