# Plugins

Engines and storages come to Storage Explorer as plugins. Install one, and every explorer uses it.

## Engines

An engine is a data library that the explorer views data with. Choose one from the status bar.

| Plugin                                             | Engine             | Formats                                                | Status       |
|----------------------------------------------------|--------------------|--------------------------------------------------------|--------------|
| [polars-support](polars-support/README.md)         | Polars             | Delta Lake, Parquet, CSV, JSON Lines, Excel            | Beta         |
| [pandas-support](pandas-support/README.md)         | pandas             | Parquet, CSV, JSON Lines, Excel                        | Beta         |
| [pyspark-support](pyspark-support/README.md)       | PySpark            | Delta Lake, Parquet, CSV, JSON Lines                   | Beta         |
| [databricks-support](databricks-support/README.md) | Databricks Connect | Delta Lake, Parquet, CSV, JSON Lines                   | Experimental |
| [duckdb-support](duckdb-support/README.md)         | DuckDB             | Delta Lake, Parquet, CSV, JSON Lines, DuckDB databases | Beta         |
| [dask-support](dask-support/README.md)             | Dask               | Parquet, CSV, JSON Lines                               | Experimental |

Polars and DuckDB query the data themselves, lazily. pandas reads the first rows only. PySpark and Databricks Connect
run the queries on Spark. Dask reads the data lazily, a partition at a time, on the Dask scheduler of the kernel.

## Storages

A storage plugin makes the explorer work better with one storage service.

| Plugin                                             | Storage                      | What it adds                                                   | Status       |
|----------------------------------------------------|------------------------------|----------------------------------------------------------------|--------------|
| [abfs-support](abfs-support/README.md)             | Azure Data Lake Storage Gen2 | Folders moved in one step, copies on the server, empty folders | Beta         |
| [databricks-support](databricks-support/README.md) | Databricks                   | Volumes, workspace files and legacy DBFS, by workspace         | Experimental |

Status:

- **Beta**: tested, and may still change between releases.
- **Experimental**: not tested where it is meant to run, e.g. on a cluster. Its extras are not in `all` and
  `all-supports`.

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
| [pyspark-support](pyspark-support/README.md)       | `pyspark`    | `pyspark-support`    | pyspark, delta-spark, pyarrow                   |
| [abfs-support](abfs-support/README.md)             | `abfs`       | `abfs-support`       | adlfs, azure-storage-file-datalake              |
| [databricks-support](databricks-support/README.md) | `databricks` | `databricks-support` | fsspec-databricks, databricks-connect           |
| [duckdb-support](duckdb-support/README.md)         | `duckdb`     | `duckdb-support`     | duckdb, pyarrow                                 |
| [dask-support](dask-support/README.md)             | `dask`       | `dask-support`       | dask, with pandas and pyarrow                   |
| All but the experimental ones                      | `all`        | `all-supports`       | All of the above, but the experimental plugins' |

[Installation](../docs/storage-explorer.md#installation) says when to choose each kind of extra. Each plugin's README
has its options.

## Writing a plugin

Your favourite library is not here yet? You, or your AI assistant, can write a plugin for it. See
[Developing plugins](../docs/development-plugin.md).
