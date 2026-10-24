"""DuckDB support for Storage Explorer.

DuckDB as an engine: the data browser on Parquet, CSV, JSON Lines, Delta Lake
tables and DuckDB databases, and code loading them.

The plugin, ``DuckDBSupport``, is found by explorers through its entry point
(``duckdb-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_duckdb_support.supports import (
    CsvByDuckDB,
    CsvByDuckDBOptions,
    DeltaLakeByDuckDB,
    DeltaLakeByDuckDBOptions,
    DuckDB,
    DuckDBDatabase,
    DuckDBDatabaseByDuckDB,
    DuckDBEngine,
    DuckDBOptions,
    JsonLinesByDuckDB,
    JsonLinesByDuckDBOptions,
    ParquetByDuckDB,
    ParquetByDuckDBOptions,
)


class DuckDBSupport(StorageExplorerPlugin):
    key = "duckdb-support"

    @property
    def format_supports(self):
        return (
            DeltaLakeByDuckDB,
            ParquetByDuckDB,
            CsvByDuckDB,
            JsonLinesByDuckDB,
            DuckDBDatabaseByDuckDB,
        )


__all__ = [
    "CsvByDuckDB",
    "CsvByDuckDBOptions",
    "DeltaLakeByDuckDB",
    "DeltaLakeByDuckDBOptions",
    "DuckDB",
    "DuckDBDatabase",
    "DuckDBDatabaseByDuckDB",
    "DuckDBEngine",
    "DuckDBOptions",
    "DuckDBSupport",
    "JsonLinesByDuckDB",
    "JsonLinesByDuckDBOptions",
    "ParquetByDuckDB",
    "ParquetByDuckDBOptions",
]
