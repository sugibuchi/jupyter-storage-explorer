# Jupyter Storage Explorer

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)

**`StorageExplorer`** is a file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the
spirit of Azure Storage Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; page through, sort and filter tables; get ready-to-run code that
loads the data into your notebook; and upload, download, move and edit files without leaving JupyterLab.

<img src="https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/storage-explorer.png" width="954" alt="StorageExplorer with a JSON Lines file open in the data browser">

This package also provides the **`DataExplorer`** widget, which lets you browse tabular data in your notebook: any
dataframe of pandas, polars, Spark, DuckDB and more. Page through, sort and filter it in the widget, then get the
result back in code.

![DataExplorer showing a Delta Lake table in a notebook](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/data-explorer.png)

## Highlights

- **`StorageExplorer`**: any fsspec storage, several in one explorer; copy and paste between storages and notebooks.
- **`DataExplorer`**: page, sort and filter any dataframe; get the result back in code.
- **Previews** of Delta Lake, Parquet, CSV, JSON, Excel, text and images, with code to load them.
- **Background file operations** with progress and Cancel; folder operations only in Unsafe mode.
- **Work in JupyterLab**: open storage files in JupyterLab's own editors and viewers, and save them back; query tables
  in tabs of their own.
- **Bookmarks**, remembered queries, transfer rules, and a JupyterLab launcher item.

## Installation

```bash
pip install jupyter-storage-explorer
```

Install the package for your storage too:

| Storage                        | Package    | Address                                              |
|--------------------------------|------------|------------------------------------------------------|
| Amazon S3                      | `s3fs`     | `s3://bucket/path`                                   |
| Azure Data Lake / Blob Storage | `adlfs`    | `abfs://container@account.dfs.core.windows.net/path` |
| Google Cloud Storage           | `gcsfs`    | `gs://bucket/path`                                   |
| Local disk, in-memory          | (included) | `/path`, `memory://`                                 |

Previewing and querying data files needs a data library, e.g. `pip install polars deltalake`; the preview tells you
which.

## Quick start

### From the JupyterLab launcher

**[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**
adds **Storage Explorer** to JupyterLab's launcher, opening the explorer in its own tab:

```bash
pip install jupyter-storage-explorer-launcher
```

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

### From Python code

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

Options after the address go to the storage package, e.g. `profile="analytics"`. Double-click a file to preview it;
right-click for everything else.

Browse a dataframe and get the rows you filtered back:

```python
import polars as pl
from jupyter_storage_explorer import DataExplorer

explorer = DataExplorer(pl.scan_parquet("s3://my-bucket/lake/sales/*.parquet"))
explorer
```

```python
explorer.result().collect()  # after filtering and sorting in the widget
```

The `notebooks` folder has a demo of each widget on sample data.

## Documentation

- **[StorageExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md)**:
  storages, using the explorer, transfer policy, formats and options.
- **[DataExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md)**: the data
  browser, `result()`, `on_change()`, `QuerySettings` and options.
- **[The launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: configuring
  its tab with `launcher.py` files.
- **[Development](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md)**: building,
  releasing, and custom icons.

## Requirements

- Python 3.11 or later
- JupyterLab 4 (other Jupyter frontends show the widgets, without drag and drop from JupyterLab's file browser)
- For querying data: polars (tested with 2.0)
