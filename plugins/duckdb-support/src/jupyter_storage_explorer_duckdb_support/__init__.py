"""DuckDB support for Storage Explorer.

DuckDB as an engine: the data browser on Parquet, CSV, JSON Lines, Delta Lake
tables and DuckDB databases, and code loading them.

The plugin, ``DuckDBSupport``, is found by explorers through its entry point
(``duckdb-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_duckdb_support.actions import (
    DUCKDB_ACTIONS,
    CsvByDuckDBOptions,
    DeltaLakeByDuckDBOptions,
    DuckDB,
    DuckDBDatabase,
    DuckDBEngine,
    DuckDBOptions,
    JsonLinesByDuckDBOptions,
    ParquetByDuckDBOptions,
    csv_as_relation,
    csv_view,
    database_code,
    database_view,
    delta_as_relation,
    delta_view,
    json_lines_as_relation,
    json_lines_view,
    parquet_as_relation,
    parquet_view,
)


class DuckDBSupport(StorageExplorerPlugin):
    key = "duckdb-support"

    @property
    def actions(self):
        return DUCKDB_ACTIONS


__all__ = [
    "DUCKDB_ACTIONS",
    "CsvByDuckDBOptions",
    "DeltaLakeByDuckDBOptions",
    "DuckDB",
    "DuckDBDatabase",
    "DuckDBEngine",
    "DuckDBOptions",
    "DuckDBSupport",
    "JsonLinesByDuckDBOptions",
    "ParquetByDuckDBOptions",
    "csv_as_relation",
    "csv_view",
    "database_code",
    "database_view",
    "delta_as_relation",
    "delta_view",
    "json_lines_as_relation",
    "json_lines_view",
    "parquet_as_relation",
    "parquet_view",
]
