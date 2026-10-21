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
