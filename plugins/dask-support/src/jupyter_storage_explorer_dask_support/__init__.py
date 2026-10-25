"""Dask support for Storage Explorer.

Dask (``dask.dataframe``) as an engine: the data browser on Parquet, CSV and
JSON Lines, and code loading them. Experimental: it is tested with Dask's
local schedulers only, not on a Dask cluster.

The plugin, ``DaskSupport``, is found by explorers through its entry point
(``dask-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_dask_support.actions import (
    DASK_ACTIONS,
    CsvByDaskOptions,
    Dask,
    DaskEngine,
    DaskOptions,
    JsonLinesByDaskOptions,
    ParquetByDaskOptions,
    csv_as_data_frame,
    csv_view,
    json_lines_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
)


class DaskSupport(StorageExplorerPlugin):
    key = "dask-support"

    @property
    def actions(self):
        return DASK_ACTIONS


__all__ = [
    "DASK_ACTIONS",
    "CsvByDaskOptions",
    "Dask",
    "DaskEngine",
    "DaskOptions",
    "DaskSupport",
    "JsonLinesByDaskOptions",
    "ParquetByDaskOptions",
    "csv_as_data_frame",
    "csv_view",
    "json_lines_as_data_frame",
    "json_lines_view",
    "parquet_as_data_frame",
    "parquet_view",
]
