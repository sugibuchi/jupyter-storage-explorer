# jupyter-storage-explorer-pyspark-support

PySpark support for Storage Explorer, the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
PySpark (or Databricks Connect) as an engine: the data browser on Spark DataFrames of Delta Lake tables, Parquet, CSV and JSON Lines, and code loading them.

```bash
pip install "jupyter-storage-explorer[pyspark]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[pyspark-support]"  # the plugin only, with the libraries you have
```

Its libraries (`pyspark`, `delta-spark`) are not its dependencies, so that installing it never
changes those of a shared environment: the first command (or `jupyter-storage-explorer-pyspark-support[full]`) installs them too.
Explorers use every plugin installed, unless their `plugin_options` disable it: `{"pyspark-support": {"enabled": False}}`
(see [Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#plugins)).

Its supports' options, in `format_options["pyspark"]` (by format, or `"*"` for all), configure the Spark session and
the reader, for the data browser and the code:

```python
StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    format_options={
        "pyspark": {
            "*": {
                "session_options": {
                    "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                    "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
                },
            },
            "csv": {"reader_options": {"mode": "DROPMALFORMED"}},
        },
    },
)
```

`session_options` go to `SparkSession.builder.config(key, value)`: with a session already running in the kernel, only
what Spark can change at run time applies. `reader_options` go to `spark.read.option(key, value)`; for CSV, they
override the defaults `header`, `inferSchema` and the separator detected (`sep`). Keys that look like credentials are
left out of the generated code.
