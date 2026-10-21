"""Polars support for Storage Explorer.

Polars as an engine: the data browser on Delta Lake tables, Parquet, CSV, JSON Lines and Excel, and code loading them.

The plugin, ``PolarsSupport``, is found by explorers through its entry point
(``polars-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_polars_support.supports import (
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    JsonByPolars,
    JsonLinesByPolars,
    ParquetByPolars,
    PolarsEngine,
    PolarsOptions,
)


class PolarsSupport(StorageExplorerPlugin):
    key = "polars-support"
    label = "Polars support for Storage Explorer"

    @property
    def format_supports(self):
        return (
            DeltaLakeByPolars,
            ParquetByPolars,
            CsvByPolars,
            ExcelByPolars,
            JsonByPolars,
            JsonLinesByPolars,
        )


__all__ = [
    "CsvByPolars",
    "DeltaLakeByPolars",
    "DeltaLakeByPolarsOptions",
    "ExcelByPolars",
    "ExcelByPolarsOptions",
    "JsonByPolars",
    "JsonLinesByPolars",
    "ParquetByPolars",
    "PolarsEngine",
    "PolarsOptions",
    "PolarsSupport",
]
