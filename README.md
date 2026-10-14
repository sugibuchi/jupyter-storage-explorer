# Jupyter Storage Explorer

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)

A file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the spirit of Azure Storage
Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; page through, sort and filter tables; get ready-to-run code that
loads the data into your notebook; and upload, download, move and edit files without leaving JupyterLab.

![StorageExplorer with a JSON Lines file open in the data browser](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/figs/storage-explorer.png)

## Highlights

- **`StorageExplorer`**: any fsspec storage, several in one explorer; copy and paste between storages and notebooks.
- **`DataExplorer`**: page, sort and filter any dataframe; get the result back in code.
- **Previews** of Delta Lake, Parquet, CSV, JSON, Excel, text and images, with code to load them.
- **Background file operations** with progress and Cancel; folder operations only in Unsafe mode.
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

Previewing and querying data files needs a data library, e.g. `pip install polars deltalake`. If one is missing, the
preview tells you what to install.

## Quick start

### From the JupyterLab launcher

The separate package **[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**
adds **Storage Explorer** to JupyterLab's launcher and command palette, opening the explorer in its own tab:

```bash
pip install jupyter-storage-explorer-launcher
```

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

### From Python code

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

The explorer appears as the cell's output. Options after the address are passed to the storage package, e.g.
`StorageExplorer("s3://my-bucket/data", profile="analytics")`. Double-click a file to preview it; right-click for
everything else.

To browse a dataframe and get the rows you filtered back:

```python
import polars as pl
from jupyter_storage_explorer import DataExplorer

explorer = DataExplorer(pl.scan_parquet("s3://my-bucket/lake/sales/*.parquet"))
explorer
```

```python
explorer.result().collect()  # after filtering and sorting in the widget
```

The `notebooks` folder has a demo of each widget (`storage_explorer.ipynb`, `data_explorer.ipynb`) on sample data made
by `make_samples.py`.

## Documentation

- **[StorageExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md)**:
  storages, using the explorer, unsafe operations, transfer policy, remembered states, supported formats, format
  options and all the options.
- **[DataExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md)**: the data
  browser, `result()`, `on_change()`, `QuerySettings` and the options.
- **[The launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: installing it
  and configuring its tab with `launcher.py` files.
- **[Development](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md)**: building from
  source, the JupyterLab extension, releasing, and customizing the explorer's icons with CSS.

## Requirements

- Python 3.11 or later
- JupyterLab 4. The widgets also show in other Jupyter frontends, but dragging files from JupyterLab's file browser
  works only in JupyterLab.
- For querying data: a recent polars (tested with polars 2.0). `DataExplorer` works with any dataframe narwhals
  supports; with polars installed, data in memory is queried with polars, which is faster.
