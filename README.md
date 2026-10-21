# Jupyter Storage Explorer

*Explore your data lake without leaving Jupyter: built for data professionals*

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)
[![Try it on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/main?urlpath=lab/tree/binder/demo.ipynb)

**`StorageExplorer`** is a file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the
spirit of Azure Storage Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; page through, sort and filter tables; get ready-to-run code that
loads the data into your notebook; and upload, download, move and edit files without leaving JupyterLab. See
[Using the explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#using-the-explorer)
for all you can do with it.

![Storage Explorer in JupyterLab: a Delta Lake table queried, files filtered, and a Markdown file edited in JupyterLab's editor and previewed](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/storage-explorer.gif)

This package also provides the **`DataExplorer`** widget, which lets you browse tabular data in your notebook: any
dataframe of pandas, polars, Spark, DuckDB and more. Page through, sort and filter it in the widget, then get the
result back in code.
See [Using the data browser](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#using-the-data-browser)
for all you can do with it.

![DataExplorer in a notebook: a Parquet file paged through, columns hidden, filtered and sorted](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/data-explorer.gif)

## Highlights

- **`StorageExplorer`**: any fsspec storage, several in one explorer; copy and paste between storages and notebooks.
- **`DataExplorer`**: page, sort and filter any dataframe; get the result back in code.
- **Previews** of Delta Lake, Parquet, CSV, JSON, Excel, text and images, with code to load them.
- **Your engine**: query data with Polars, pandas or PySpark (also Databricks Connect), chosen from the status bar.
- **Plugins** for engines and storages: install one, and every explorer uses it; they never change the data libraries
  of a shared environment.
- **Background file operations** with progress and Cancel; folder operations only in Unsafe mode.
- **Work in JupyterLab**: open storage files in JupyterLab's own editors and viewers, and save them back; view tables
  and files in tabs of their own.
- **Bookmarks**, remembered queries, transfer rules, and a JupyterLab launcher item.

## Installation

```bash
pip install "jupyter-storage-explorer[polars]"
```

`[polars]` adds the plugin previewing and querying data with Polars, and Polars itself. Plugins for other engines and
storages are extras too; `<name>-support` installs a plugin alone, using the libraries you have:

| Extra     | Plugin                                                                                     |
|-----------|--------------------------------------------------------------------------------------------|
| `polars`  | Polars (with deltalake and fastexcel): Delta Lake, Parquet, CSV, JSON Lines, Excel         |
| `pandas`  | pandas (with PyArrow and openpyxl): Parquet, CSV, JSON Lines, Excel                        |
| `pyspark` | PySpark or Databricks Connect (with delta-spark): Delta Lake, Parquet, CSV, JSON Lines     |
| `abfs`    | Azure Data Lake Storage Gen2: folders moved in one step, copies on the server (with adlfs) |

Install the package for your storage too:

| Storage                        | Package    | Address                                              |
|--------------------------------|------------|------------------------------------------------------|
| Amazon S3                      | `s3fs`     | `s3://bucket/path`                                   |
| Azure Data Lake / Blob Storage | `adlfs`    | `abfs://container@account.dfs.core.windows.net/path` |
| Google Cloud Storage           | `gcsfs`    | `gs://bucket/path`                                   |
| Local disk, in-memory          | (included) | `/path`, `memory://`                                 |

Without an engine plugin, the explorer still browses, moves and previews text, Markdown, JSON and images.

## Quick start

**Try it without installing anything**:
[open the demo on Binder](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/main?urlpath=lab/tree/binder/demo.ipynb),
a made-up data lake in a notebook and in
the launcher's tab (it may take a minute to start).

### From the JupyterLab launcher

**[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**
adds **Storage Explorer** to JupyterLab's launcher, opening the explorer in its own tab:

```bash
pip install "jupyter-storage-explorer-launcher[polars]"
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
  storages, using the explorer, transfer policy, formats, working with it from Python and options.
- **[DataExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md)**: the data
  browser, `result()`, `on_change()`, `QuerySettings` and options.
- **[The launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: configuring
  its tab with `launcher.py` files.
- **[Development](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md)**: building,
  releasing, and custom icons.
- **[Developing plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT_PLUGIN.md)**:
  formats, engines, file operations and storages of your own, packaged as plugins.

## Requirements

- Python 3.11 or later
- JupyterLab 4.0 or later (other Jupyter frontends show the widgets, without drag and drop from JupyterLab's file
  browser)
- For querying data: an engine plugin, e.g. `jupyter-storage-explorer[polars]` (Polars, tested with 2.0)

## Why Storage Explorer?

Storage Explorer aims to be a **data-aware file explorer for large data lakes**, made for the daily work of data
scientists and engineers. Rather than adding data lake access to JupyterLab's file browser, a narrow sidebar, it is a
widget in JupyterLab's main area, in a notebook or a tab of its own, with room for what working with data needs:

- **Built for large folders**: data lakes often hold thousands of items in one folder (partitions, part files, daily
  drops). The list is paged, sorted and filtered as you type, regular expressions included; folders of tens of
  thousands of items are listed by the kernel, a page at a time. Moving, copying, deleting and uploading run in the
  background, with their progress and Cancel, so the explorer stays usable while thousands of files move.
- **Preview as you browse**: tree, list and preview side by side. Click through files and see each one at once,
  without opening and closing tabs.
- **Tables, not just files**: Delta Lake tables and partitioned Parquet datasets are recognised as tables, not
  folders. Open them in the data browser to choose among hundreds of columns and filter and sort the data where it
  lives, with the engine you choose (Polars, pandas, or one of your own).
- **From browsing to code**: copy ready-to-run code to load a file or table with polars, pandas, PySpark and more, or
  the URLs of the files you selected, ready for any library. In Python, `folder_location` and `selected_locations`
  give the folder shown and the files selected, with their URLs.
- **Part of your notebook**: explorers are widgets, placed in your notebook next to your analysis. Your code can
  follow what you browse (`on_change()`, `on_query_change()`): a chart of the file you click, redrawn as you filter it
  in the data browser (`query_result()`). `DataExplorer` brings the same data browser to any dataframe, and gives the
  rows you filtered back to your code (`result()`). See
  [Working with the explorer from Python](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#working-with-the-explorer-from-python).
- **At home in JupyterLab**: drag files from JupyterLab's file browser into an explorer to upload them to a storage,
  or onto the file browser to download them to the server. Split the main area to put explorers side by side, in
  notebooks or tabs of their own, and drag files from one storage to another, e.g. from S3 to Azure. Files open in
  JupyterLab's own editors, and tables in a tab of their own.
- **Safe by default**: in a data lake, a folder is often a whole table. Folders can't be moved, copied, renamed or
  deleted by a stray drag: that takes
  [Unsafe mode](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#unsafe-operations),
  which turns itself off after one operation. Teams can also restrict where files may go with a
  [transfer policy](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy).
- **Runs in your kernel**: with your credentials and your libraries, and no server setup.

It complements JupyterLab's file browser rather than replacing it.
