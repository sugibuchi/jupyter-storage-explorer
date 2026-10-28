"""Azure Data Lake Storage support for Storage Explorer.

Azure Data Lake Storage Gen2: folders moved in one step, copies within an account on the server, empty folders.

The plugin, ``AbfsSupport``, is found by explorers through its entry point
(``abfs-support``); its libraries are installed with the "full" extra."""

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer.util import option_field
from jupyter_storage_explorer_abfs_support.operations import (
    AzureDataLakeGen2Operation,
)


@dataclass(frozen=True, kw_only=True)
class AbfsSupportOptions(StorageExplorerPluginOptions):
    """abfs-support's options (``plugin_options={"abfs-support": {...}}``)."""

    concurrency: int = option_field(
        (
            "The most files copied at once on the server "
            "(`AzureDataLakeGen2Operation`'s `concurrency`)."
        ),
        default=64,
    )


class AbfsSupport(StorageExplorerPlugin):
    key = "abfs-support"
    options_model = AbfsSupportOptions
    options: AbfsSupportOptions

    @property
    def filesystem_operations(self):
        return (AzureDataLakeGen2Operation(concurrency=self.options.concurrency),)


__all__ = [
    "AbfsSupport",
    "AbfsSupportOptions",
    "AzureDataLakeGen2Operation",
]
