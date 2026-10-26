# Jupyter Storage Explorer

*There's no place like Jupyter: explore your data lake without leaving home*

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![Python versions](https://img.shields.io/pypi/pyversions/jupyter-storage-explorer)](https://pypi.org/project/jupyter-storage-explorer/)
[![License](https://img.shields.io/pypi/l/jupyter-storage-explorer)](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/LICENSE)
[![CI](https://github.com/sugibuchi/jupyter-storage-explorer/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/sugibuchi/jupyter-storage-explorer/actions/workflows/ci.yaml)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)
[![Try it on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/v0.24.0?urlpath=lab/tree/binder/demo.ipynb)

**`StorageExplorer`** is a file explorer for cloud storage and data lakes, right inside Jupyter, in the spirit of Azure
Storage Explorer. It is built on [fsspec](https://filesystem-spec.readthedocs.io/), so it reaches every storage fsspec
does: S3, Azure, Google Cloud Storage, SFTP, Hugging Face and many more. See
[Using the explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#using-the-explorer).

![Storage Explorer in JupyterLab: a Delta Lake table queried, files filtered, and a Markdown file edited in JupyterLab's editor and previewed](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/storage-explorer.gif)

**`DataExplorer`** browses any dataframe in your notebook: pandas, polars, Spark, DuckDB and more, through
[narwhals](https://narwhals-dev.github.io/narwhals/). See
[Using the data browser](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#using-the-data-browser).

![DataExplorer in a notebook: a Parquet file paged through, columns hidden, filtered and sorted](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/docs/figs/data-explorer.gif)

## Highlights

- **`StorageExplorer`**: one explorer to browse them all.
  - Local disks, cloud storage and every other
    [storage fsspec implements](https://filesystem-spec.readthedocs.io/en/latest/api.html#implementations).
  - [Several storages side by side](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#several-storages-in-one-explorer)
    in one explorer.
- **`DataExplorer`**: a table widget for your dataframes, more than meets the eye.
  - Page, sort and filter large tables in your data lake.
  - [Live mode](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#live-and-in-memory):
    browse terabytes of data in Jupyter. Each page is a query run where the data is, so only the rows shown come back,
    never the whole table.
  - [Get the result back in code](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md#the-result-in-code).
- **[Launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: right at home in
  your Jupyter.
  - Open the explorer in a tab or in the side panel.
  - [Edit storage files](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#edit-files)
    in JupyterLab's editors.
  - Copy and paste, or
    [drag and drop](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#drag-and-drop),
    files between explorers.
- **Previews**: look before you load.
  - [Delta Lake, Parquet, CSV, JSON, Excel, DuckDB databases, text and images](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#supported-formats)
    open at a click.
  - Ready-to-run code loads them into your notebook.
- **Multi-engine support**: data professionals, start your engines.
  - Plug in your favourite data library:
    [Polars, pandas, DuckDB, PySpark or Dask](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/README.md).
  - Browse data with it on the fly, and switch engines at any time.
  - Get code for each engine installed.
- **Actions and plugins**: your explorer, your way.
  - Another data library, or code snippets of your own? Write a few functions as
    [actions](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/action-development-guide.md),
    offered beside the explorer's own.
  - A chart or a map of a file? Return any Jupyter widget from an action: the explorer shows it.
  - A complete extension, for another storage or data framework? Develop a
    [plugin](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/plugin-development-guide.md) with
    your AI assistant: its guide is written for both of you.
- **Safe file operations**: keep calm and copy on.
  - Copy, move and delete large folders
    [in the background](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#background-operations),
    with progress and Cancel.
  - Folder operations wait for
    [Unsafe mode](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#unsafe-operations).
  - [Transfer rules](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy)
    keep data where it may go.
- **Bookmarks**: there and back again.
  - [Bookmarks](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#bookmarks)
    bring you back to your folders.
  - [Remembered queries](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#remembered-states)
    bring back your sorting and filters.

## Requirements

- Python 3.11 or later.
- JupyterLab 4.0 or later. Other Jupyter frontends show the widgets, without drag and drop from JupyterLab's file
  browser.
- For querying data: an engine plugin, e.g. `jupyter-storage-explorer[polars]` (Polars, tested with 2.0).

## Quick start

**Try it without installing anything**:
[open the demo on Binder](https://mybinder.org/v2/gh/sugibuchi/jupyter-storage-explorer/v0.24.0?urlpath=lab/tree/binder/demo.ipynb),
a made-up data lake in a notebook and in the launcher's tab. It may take a minute to start.

### From the JupyterLab launcher

**[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**
adds **Storage Explorer** to JupyterLab's launcher, opening the explorer in its own tab, and to the left side bar:

```bash
pip install "jupyter-storage-explorer-launcher[polars]"
```

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

See the launcher's [Installation](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md#installation)
for its extras, and installing it from a notebook.

### From Python code

```bash
pip install "jupyter-storage-explorer[polars]"
```

This installs only the widgets, for notebooks. The integration with JupyterLab's UI, e.g. drag and drop with its file
browser, comes with the launcher package above.

`[polars]` adds the Polars plugin with Polars itself. Other engines and storages are extras too:
[Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/README.md) lists all of them.

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

Keyword arguments after the address go to fsspec, e.g. `profile="analytics"` for S3.

The [`notebooks`](https://github.com/sugibuchi/jupyter-storage-explorer/tree/main/notebooks) folder has a demo of each
widget on sample data.

See [Installation](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#installation)
for the storage packages and the other options.

## Documentation

- **[StorageExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md)**:
  the file browser.
- **[DataExplorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/data-explorer.md)**: the table
  widget for dataframes.
- **[Launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)**: StorageExplorer
  integrated into JupyterLab.
- **[Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/README.md)**: the engines and
  storages you can add, with their extras.
- **[Writing actions](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/action-development-guide.md)**:
  menu items of your own, for views, code snippets and more.
- **[Writing plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/plugin-development-guide.md)**:
  distribution packages of actions, filesystem support and more.
- **[Development](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md)**: building,
  releasing, and custom icons.

## Technologies

Storage Explorer is made possible by these open-source projects. Our thanks to their authors and contributors.

- **[fsspec](https://filesystem-spec.readthedocs.io/)**: filesystem interfaces for Python. Used for all storage access.
- **[narwhals](https://narwhals-dev.github.io/narwhals/)**: a compatibility layer between dataframe libraries. Used for
  the data browser's queries.
- **[anywidget](https://anywidget.dev/)**: a framework for custom Jupyter widgets. Used for both explorers' frontends.

## License

[MIT](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/LICENSE). To contribute, see
[Development](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md); to report a
vulnerability, see [Security](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/SECURITY.md).
