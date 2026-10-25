"""pandas support for Storage Explorer.

pandas as an engine: the data browser on the first rows of Parquet, CSV, JSON Lines and Excel files, and code loading them.

The plugin, ``PandasSupport``, is found by explorers through its entry point
(``pandas-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_pandas_support.supports import (
    PANDAS_ACTIONS,
    CsvByPandasOptions,
    ExcelByPandasOptions,
    JsonByPandasOptions,
    JsonLinesByPandasOptions,
    Pandas,
    PandasEngine,
    PandasOptions,
    ParquetByPandasOptions,
    csv_as_data_frame,
    csv_view,
    excel_as_data_frame,
    excel_view,
    json_as_data_frame,
    json_lines_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
)


class PandasSupport(StorageExplorerPlugin):
    key = "pandas-support"

    @property
    def actions(self):
        return PANDAS_ACTIONS


__all__ = [
    "PANDAS_ACTIONS",
    "CsvByPandasOptions",
    "ExcelByPandasOptions",
    "JsonByPandasOptions",
    "JsonLinesByPandasOptions",
    "Pandas",
    "PandasEngine",
    "PandasOptions",
    "PandasSupport",
    "ParquetByPandasOptions",
    "csv_as_data_frame",
    "csv_view",
    "excel_as_data_frame",
    "excel_view",
    "json_as_data_frame",
    "json_lines_as_data_frame",
    "json_lines_view",
    "parquet_as_data_frame",
    "parquet_view",
]
