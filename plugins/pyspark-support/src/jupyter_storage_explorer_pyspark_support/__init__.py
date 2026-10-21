"""PySpark support for Storage Explorer.

PySpark (or Databricks Connect) as an engine: the data browser on Spark DataFrames of Delta Lake tables, Parquet, CSV and JSON Lines, and code loading them.

The plugin, ``PySparkSupport``, is found by explorers through its entry point
(``pyspark-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_pyspark_support.supports import (
    CsvByPySpark,
    DeltaLakeByPySpark,
    JsonLinesByPySpark,
    ParquetByPySpark,
    PySparkEngine,
    spark_session,
    spark_url,
)


class PySparkSupport(StorageExplorerPlugin):
    key = "pyspark-support"

    @property
    def format_supports(self):
        return (
            DeltaLakeByPySpark,
            ParquetByPySpark,
            CsvByPySpark,
            JsonLinesByPySpark,
        )


__all__ = [
    "CsvByPySpark",
    "DeltaLakeByPySpark",
    "JsonLinesByPySpark",
    "ParquetByPySpark",
    "PySparkEngine",
    "PySparkSupport",
    "spark_session",
    "spark_url",
]
