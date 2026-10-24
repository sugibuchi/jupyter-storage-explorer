# Plugins

Engines and storages come to Storage Explorer as plugins. Install one, and every explorer uses it.

## Engines

An engine is a data library that the explorer views data with. Choose one from the status bar.

| Plugin                                                 | Engine             | Formats                                         |
|--------------------------------------------------------|--------------------|-------------------------------------------------|
| [polars-support](polars-support/README.md)             | Polars             | Delta Lake, Parquet, CSV, JSON Lines, Excel     |
| [pandas-support](pandas-support/README.md)             | pandas             | Parquet, CSV, JSON Lines, Excel                 |
| [pyspark-support](pyspark-support/README.md)           | PySpark            | Delta Lake, Parquet, CSV, JSON Lines            |
| [databricks-support](databricks-support/README.md)     | Databricks Connect | Delta Lake, Parquet, CSV, JSON Lines            |

Polars queries the data itself, lazily. pandas reads the first rows only. PySpark and Databricks Connect run the
queries on Spark.

## Storages

A storage plugin makes the explorer work better with one storage service.

| Plugin                                             | Storage                      | What it adds                                                  |
|----------------------------------------------------|------------------------------|---------------------------------------------------------------|
| [abfs-support](abfs-support/README.md)             | Azure Data Lake Storage Gen2 | Folders moved in one step, copies on the server, empty folders |
| [databricks-support](databricks-support/README.md) | Databricks                   | Volumes, workspace files and legacy DBFS, by workspace         |

databricks-support is experimental.

## Installation

Each plugin comes with two extras of the explorer, and of the launcher:

```bash
pip install "jupyter-storage-explorer[polars]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[polars-support]"  # the plugin only, with the libraries you have
```

| Plugin                                             | Full extra   | Support-only extra   | Libraries of the full extra                     |
|----------------------------------------------------|--------------|----------------------|-------------------------------------------------|
| [polars-support](polars-support/README.md)         | `polars`     | `polars-support`     | polars, deltalake, fastexcel, pyarrow           |
| [pandas-support](pandas-support/README.md)         | `pandas`     | `pandas-support`     | pandas, pyarrow, openpyxl                       |
| [pyspark-support](pyspark-support/README.md)       | `pyspark`    | `pyspark-support`    | pyspark, delta-spark                            |
| [abfs-support](abfs-support/README.md)             | `abfs`       | `abfs-support`       | adlfs, azure-storage-file-datalake              |
| [databricks-support](databricks-support/README.md) | `databricks` | `databricks-support` | fsspec-databricks, databricks-connect           |
| All but the experimental ones                      | `all`        | `all-supports`       | All of the above, but the experimental plugins' |

[Installation](../docs/storage-explorer.md#installation) says when to choose each kind of extra. Each plugin's README
has its options.

## Writing a plugin

Your favourite library is not here yet? You, or your AI assistant, can write a plugin for it. See
[Developing plugins](../docs/development-plugin.md).
