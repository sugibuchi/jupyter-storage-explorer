"""PySpark support for Storage Explorer.

PySpark as an engine: the data browser on Spark DataFrames of Delta Lake tables, Parquet, CSV and JSON Lines, and code loading them.

The plugin, ``PySparkSupport``, is found by explorers through its entry point
(``pyspark-support``); its libraries are installed with the "full" extra."""

from jupyter_storage_explorer import StorageExplorerPlugin
from jupyter_storage_explorer_pyspark_support.supports import (
    PYSPARK_ACTIONS,
    PYSPARK_SESSIONS,
    SPARK_PROTOCOLS,
    CsvByPySparkOptions,
    DeltaLakeByPySparkOptions,
    JsonLinesByPySparkOptions,
    ParquetByPySparkOptions,
    PySpark,
    PySparkEngine,
    PySparkOptions,
    SparkSessions,
    csv_as_data_frame,
    csv_view,
    delta_as_data_frame,
    delta_view,
    json_lines_as_data_frame,
    json_lines_view,
    parquet_as_data_frame,
    parquet_view,
    spark_csv_code,
    spark_csv_view,
    spark_delta_code,
    spark_delta_view,
    spark_json_lines_code,
    spark_json_lines_view,
    spark_parquet_code,
    spark_parquet_view,
    spark_reads,
    spark_rows,
    spark_session,
    spark_url,
)


class PySparkSupport(StorageExplorerPlugin):
    key = "pyspark-support"

    @property
    def actions(self):
        return PYSPARK_ACTIONS


__all__ = [
    "PYSPARK_ACTIONS",
    "PYSPARK_SESSIONS",
    "SPARK_PROTOCOLS",
    "CsvByPySparkOptions",
    "DeltaLakeByPySparkOptions",
    "JsonLinesByPySparkOptions",
    "ParquetByPySparkOptions",
    "PySpark",
    "PySparkEngine",
    "PySparkOptions",
    "PySparkSupport",
    "SparkSessions",
    "csv_as_data_frame",
    "csv_view",
    "delta_as_data_frame",
    "delta_view",
    "json_lines_as_data_frame",
    "json_lines_view",
    "parquet_as_data_frame",
    "parquet_view",
    "spark_csv_code",
    "spark_csv_view",
    "spark_delta_code",
    "spark_delta_view",
    "spark_json_lines_code",
    "spark_json_lines_view",
    "spark_parquet_code",
    "spark_parquet_view",
    "spark_reads",
    "spark_rows",
    "spark_session",
    "spark_url",
]
