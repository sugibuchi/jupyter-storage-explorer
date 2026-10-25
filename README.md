# Jupyter Storage Explorer

*Explore your data lake without leaving Jupyter: built for data professionals*

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)
[![Try it on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/main?urlpath=lab/tree/binder/demo.ipynb)

**`StorageExplorer`** is a file explorer for cloud storage and data lakes, right inside Jupyter, in the spirit of Azure
Storage Explorer. See
[Using the explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#using-the-explorer).

![Storage Explorer in JupyterLab: a Delta Lake table queried, files filtered, and a Markdown file edited in JupyterLab's editor and previewed](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/storage-explorer.gif)

**`DataExplorer`** browses any dataframe in your notebook: pandas, polars, Spark, DuckDB and more. See
[Using the data browser](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#using-the-data-browser).

![DataExplorer in a notebook: a Parquet file paged through, columns hidden, filtered and sorted](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/data-explorer.gif)

## Highlights

- **`StorageExplorer`**: one explorer to browse them all. S3, Azure, Google Cloud Storage, local disks and anything else
  fsspec reaches,
  [side by side](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#several-storages-in-one-explorer).
- **`DataExplorer`**: a table widget for your dataframes, more than meets the eye. Page, sort and filter large tables in
  your data lake, and
  [get the result back in code](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#the-result-in-code).
- **[Launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: right at home in
  your Jupyter. Open the explorer in a tab or in the side panel,
  [edit storage files](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#edit-files),
  and copy and paste or
  [drag and drop](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#drag-and-drop)
  files between explorers, and more.
- **Previews**: look before you load.
  [Delta Lake, Parquet, CSV, JSON, Excel, DuckDB databases, text and images](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#supported-formats)
  open at a click, with ready-to-run code that loads them into your notebook.
- **Plugin support**: data professionals, start your engines. Plug your favourite data library, such as
  [Polars, pandas, DuckDB, PySpark or Dask](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/README.md), into
  the explorer, and browse data with it on the fly. Not supported yet? You, or your AI assistant, can
  write a plugin for it: see [Developing plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/development-plugin.md).
  Or drop a few functions in
  [a file of your own](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#actions-of-your-own),
  and every explorer views your formats your way.
- **Safe file operations**: keep calm and copy on. Copy, move and delete large folders
  [in the background](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#background-operations),
  with progress and Cancel. Folder operations wait for
  [Unsafe mode](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#unsafe-operations),
  and [transfer rules](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy)
  keep data where it may go.
- **Bookmarks**: there and back again.
  [Bookmarks](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#bookmarks) and
  [remembered queries](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#remembered-states)
  bring you back where you left off.

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
[Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/README.md) for all of them, and
[Installation](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#installation)
for the storage packages.

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
