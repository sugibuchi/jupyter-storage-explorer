"""pandas support for Storage Explorer.

pandas as an engine: the data browser on the first rows of Parquet, CSV, JSON Lines and Excel files, and code loading them.

The plugin, ``PandasSupport``, is found by explorers through its entry point
(``pandas-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_pandas_support.supports import (
    CsvByPandas,
    ExcelByPandas,
    JsonByPandas,
    JsonLinesByPandas,
    PandasEngine,
    PandasOptions,
    ParquetByPandas,
)


class PandasSupport(StorageExplorerPlugin):
    key = "pandas-support"

    @property
    def format_supports(self):
        return (
            ParquetByPandas,
            CsvByPandas,
            ExcelByPandas,
            JsonByPandas,
            JsonLinesByPandas,
        )


__all__ = [
    "CsvByPandas",
    "ExcelByPandas",
    "JsonByPandas",
    "JsonLinesByPandas",
    "PandasEngine",
    "PandasOptions",
    "PandasSupport",
    "ParquetByPandas",
]
