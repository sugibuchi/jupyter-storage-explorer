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
- **Your engine**: query data with Polars, pandas or PySpark, chosen from the status bar.
- **Plugins** for engines and storages: install one, and every explorer uses it; they never change the data libraries
  of a shared environment. Databricks volumes and Databricks Connect come with an experimental one.
- **Background file operations** with progress and Cancel; folder operations only in Unsafe mode, or always, or never.
- **Work in JupyterLab**: open storage files in JupyterLab's own editors and viewers, and save them back; view tables
  and files in tabs of their own.
- **Bookmarks**, remembered queries, transfer rules, a JupyterLab launcher item and a side panel.

## Quick start

**Try it without installing anything**:
[open the demo on Binder](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/main?urlpath=lab/tree/binder/demo.ipynb),
a made-up data lake in a notebook and in
the launcher's tab (it may take a minute to start).

### From the JupyterLab launcher

**[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**
adds **Storage Explorer** to JupyterLab's launcher, opening the explorer in its own tab, and to the left side bar:

```bash
pip install "jupyter-storage-explorer-launcher[polars]"
```

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

### From Python code

```bash
pip install "jupyter-storage-explorer[polars]"
```

`[polars]` adds the Polars plugin with Polars itself; other engines and storages are extras too, e.g.
`[polars-support]` for the plugin alone, using the libraries you have (recommended in carefully set up kernels). See
[Installation](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#installation)
for all of them and the storage packages.

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

Options after the address go to the storage package, e.g. `profile="analytics"`. Double-click a file to preview it;
right-click for everything else. With the launcher installed, files that JupyterLab can show open in its editors
instead.

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
- **[Developing plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/development-plugin.md)**:
  formats, engines, file operations and storages of your own, packaged as plugins.

## Requirements

- Python 3.11 or later
- JupyterLab 4.0 or later (other Jupyter frontends show the widgets, without drag and drop from JupyterLab's file
  browser)
- For querying data: an engine plugin, e.g. `jupyter-storage-explorer[polars]` (Polars, tested with 2.0)

## Why Storage Explorer?

A **data-aware file explorer for large data lakes**, in JupyterLab's main area (a notebook or a tab), with room for
what working with data needs; it complements JupyterLab's file browser rather than replacing it.

- **Large folders**: paged, sorted and filtered as you type; tens of thousands of items listed by the kernel; file
  operations in the background, with progress and Cancel.
- **Tables, not just files**: Delta Lake tables and partitioned Parquet datasets open in the data browser, queried
  where they live with the engine you choose.
- **From browsing to code**: ready-to-run code and URLs for what you select; your code can follow what you browse
  ([from Python](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#working-with-the-explorer-from-python)).
- **At home in JupyterLab**: drag files to and from its file browser and between storages; edit files in its editors;
  keep an explorer in its side bar, beside your notebooks
  ([the launcher's side panel](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)).
- **Safe by default**: folders are moved, copied, renamed or deleted only in
  [Unsafe mode](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#unsafe-operations),
  for one operation.
- **Runs in your kernel**: with your credentials and your libraries, and no server setup.
