"""Dask support for Storage Explorer.

Dask (``dask.dataframe``) as an engine: the data browser on Parquet, CSV and
JSON Lines, and code loading them. Experimental: it is tested with Dask's
local schedulers only, not on a Dask cluster.

The plugin, ``DaskSupport``, is found by explorers through its entry point
(``dask-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_dask_support.supports import (
    CsvByDask,
    CsvByDaskOptions,
    Dask,
    DaskEngine,
    DaskOptions,
    JsonLinesByDask,
    JsonLinesByDaskOptions,
    ParquetByDask,
    ParquetByDaskOptions,
    dask_rows,
)


class DaskSupport(StorageExplorerPlugin):
    key = "dask-support"

    @property
    def format_supports(self):
        return (ParquetByDask, CsvByDask, JsonLinesByDask)


__all__ = [
    "CsvByDask",
    "CsvByDaskOptions",
    "Dask",
    "DaskEngine",
    "DaskOptions",
    "DaskSupport",
    "JsonLinesByDask",
    "JsonLinesByDaskOptions",
    "ParquetByDask",
    "ParquetByDaskOptions",
    "dask_rows",
]
