"""Polars support for Storage Explorer.

Polars as an engine: the data browser on Delta Lake tables, Parquet, CSV, JSON Lines and Excel, and code loading them.

The plugin, ``PolarsSupport``, is found by explorers through its entry point
(``polars-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_polars_support.supports import (
    POLARS_ACTIONS,
    CsvByPolarsOptions,
    DeltaLakeByPolarsOptions,
    ExcelByPolarsOptions,
    FsspecCodeOptions,
    JsonByPolarsOptions,
    JsonLinesByPolarsOptions,
    ParquetByPolarsOptions,
    Polars,
    PolarsEngine,
    PolarsOptions,
    csv_as_data_frame,
    csv_view,
    delta_as_data_frame,
    delta_as_lazy_frame,
    delta_view,
    excel_as_data_frame,
    excel_view,
    json_as_data_frame,
    json_lines_as_data_frame,
    json_lines_as_lazy_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_as_lazy_frame,
    parquet_view,
)


class PolarsSupport(StorageExplorerPlugin):
    key = "polars-support"

    @property
    def actions(self):
        return POLARS_ACTIONS


__all__ = [
    "POLARS_ACTIONS",
    "CsvByPolarsOptions",
    "DeltaLakeByPolarsOptions",
    "ExcelByPolarsOptions",
    "FsspecCodeOptions",
    "JsonByPolarsOptions",
    "JsonLinesByPolarsOptions",
    "ParquetByPolarsOptions",
    "Polars",
    "PolarsEngine",
    "PolarsOptions",
    "PolarsSupport",
    "csv_as_data_frame",
    "csv_view",
    "delta_as_data_frame",
    "delta_as_lazy_frame",
    "delta_view",
    "excel_as_data_frame",
    "excel_view",
    "json_as_data_frame",
    "json_lines_as_data_frame",
    "json_lines_as_lazy_frame",
    "json_lines_view",
    "parquet_as_data_frame",
    "parquet_as_lazy_frame",
    "parquet_view",
]
