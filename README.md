# Jupyter Storage Explorer

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer?color=blue)](https://pypi.org/project/jupyter-storage-explorer/)
[![codecov](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer/graph/badge.svg?token=TFA12UL1IQ)](https://codecov.io/gh/sugibuchi/jupyter-storage-explorer)

A file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the spirit of Azure Storage
Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; page through, sort and filter tables; get ready-to-run code that
loads the data into your notebook; and upload, download, move and edit files without leaving JupyterLab.

Two widgets:

- **`StorageExplorer`**: the file explorer, with previews and the data browser.
- **`DataExplorer`**: the data browser alone, for a dataframe (pandas, polars, Spark, DuckDB, ...).

![StorageExplorer with a JSON Lines file open in the data browser](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/figs/storage-explorer.png)

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

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

The explorer appears as the cell's output. Other examples:

```python
StorageExplorer()  # the current folder
StorageExplorer("abfs://lake@myaccount.dfs.core.windows.net/raw")  # Azure Data Lake
StorageExplorer("s3://my-bucket/data", profile="analytics")  # Amazon S3, with options
StorageExplorer("gs://my-bucket", token="google_default")  # Google Cloud
```

Options after the address (like `profile` above) are passed to the storage package, for example to choose credentials.

To browse a dataframe, see [DataExplorer](#dataexplorer-browse-a-dataframe). The `notebooks` folder has a demo of each
widget (`storage_explorer.ipynb`, `data_explorer.ipynb`) on sample data made by `make_samples.py`.

### From the JupyterLab launcher

The separate package **[`jupyter-storage-explorer-launcher`](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)** adds **Storage Explorer** to
JupyterLab's launcher and command palette, opening the explorer in its own tab on the launcher's folder (the one the
file browser showed):

```bash
pip install jupyter-storage-explorer-launcher
```

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

What the tab shows is configured with `launcher.py` files, for the whole system and for each user; see the
[launcher's README](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md).

### Several storages in one explorer

Give each storage a name; a drop-down on the left of the address bar switches between them, and each one remembers the
folder you were in.

```python
StorageExplorer(
    filesystems={
        "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
        "Raw files (S3)": "s3://my-bucket/raw",
        "Local": "/home/me/data",
    },
)
```

## Using the explorer

- **Browse**: click folders in the tree or list; ↑ goes up, ⟳ refreshes. Ctrl+click (⌘+click) selects several items.
  The list shows 100 items per page (◀ ▶ above it).
- **Filter**: type in the fields above the tree and the list (and in **Select columns** of the data browser) to show
  only names containing the text, or matching a regular expression with **.\***. Case is ignored; ✕ or Esc clears.
- **Preview**: double-click a file, or **Preview** (with nothing selected: the current folder, e.g. a Delta Lake table).
  Tables open in the [data browser](#query-data).
- **Right-click**: Preview as, Edit, Python code to load the data, Copy, Cut, Paste, Delete, Create a folder, Download
  to local or to JupyterLab (see [Options](#storageexplorer-options)), Copy URL.
- **Copy, cut and paste** work between storages and between explorers, also in other notebooks: **Cut**, then
  **Move here**, moves files to another storage.
- **Drag and drop**: drop files from JupyterLab's file browser or your computer to upload them; drag files onto a folder
  to move them, or onto JupyterLab's file browser to download them (needs [the launcher](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md)).
- **In the background**: moving, deleting, pasting and downloading to JupyterLab run while you keep browsing, with
  their progress above the status bar and **Cancel**.

### Unsafe operations

Folder operations need **Unsafe mode**, turned on with the slider in the status bar:

| Operation              | How                                                 |
|------------------------|-----------------------------------------------------|
| Move folders           | Drag a folder onto another folder, or right-click → **Cut**, then **Move here** on a folder. |
| Copy and paste folders | Right-click → **Copy**, then **Paste** on a folder.                                          |
| Delete folders         | Right-click → **Delete** (with everything in it).                                            |

## Query data

With [polars](https://pola.rs) installed (plus `deltalake` for Delta Lake, `fastexcel` for Excel), tables open in a data
browser that reads 1,000 rows at a time:

- ◀ ▶ to page, click a column name to sort, its funnel to filter (*Null / empty*, *Range*, *Contains*, *Regex*).
- **Select columns** to hide columns, drag a header's edge to resize, **Reset** to clear filters, **⟳** to reload.
- **Live** / **In memory** (top right): query the data itself, or read its first 100,000 rows into memory once and
  query those (faster, but filters and sorting then apply to those rows only). Data of up to 1,000 rows is always
  kept in memory.

Filters, sorting, hidden columns and widths are remembered per table until the kernel restarts, or in a file with
`query_settings=QuerySettingsStore("query-settings.json")` (from `jupyter_storage_explorer.query`). polars reads the
data with the credentials in the environment, not the explorer's options.

## Supported formats

| Format                                                       | Name         | Preview                       | Query data | Load with                                           |
|--------------------------------------------------------------|--------------|-------------------------------|------------|-----------------------------------------------------|
| Delta Lake tables                                            | `delta`      | First rows                    | ✓         | polars (with deltalake), PySpark (with delta-spark) |
| Parquet files, and folders of them (e.g. Spark, Hive output) | `parquet`    | First rows                    | ✓         | polars, pandas, PySpark                             |
| CSV, TSV                                                     | `csv`        | First rows                    | ✓         | polars, pandas, PySpark                             |
| JSON Lines                                                   | `json-lines` | First records                 | ✓         | polars, pandas, PySpark                             |
| JSON                                                         | `json`       | Collapsible tree              |            | Python, polars, pandas                              |
| Excel (`.xlsx`)                                              | `excel`      | First rows of the first sheet | ✓         | polars, pandas                                      |
| Markdown                                                     | `markdown`   | Rendered                      |            | Python                                              |
| Text, code, configuration (YAML, SQL, Python, …)             | `text`       | With syntax highlighting      |            | Python                                              |
| Images (PNG, JPEG, GIF, SVG, …)                              | `image`      | Shown                         |            | Pillow                                              |

The name identifies the format in CSS (see
[Customizing icons](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md#customizing-icons)).

### Format options

`format_options` is one dictionary for all formats; each format uses the options it takes. Options are named after the
library they are for, and the ones for a single format also after the format:

```python
StorageExplorer(
    "s3://my-bucket/lake",
    format_options={
        "polars_storage_options": {"aws_region": "eu-west-1"},
        "pandas_storage_options": {"anon": False},
        "polars_delta_use_pyarrow": True,
    },
)
```

| Option                         | Formats                                         | Meaning                                                                                                               |
|--------------------------------|-------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `polars_storage_options`       | `delta`, `parquet`, `csv`, `json-lines`         | polars' `storage_options` (object_store's names, not fsspec's), in the preview, the data browser and the polars code. |
| `polars_credential_provider`   | `delta`, `parquet`, `csv`, `json-lines`         | polars' `credential_provider`, in the preview and the data browser (not in the code).                                 |
| `pandas_storage_options`       | `parquet`, `csv`, `json-lines`, `json`, `excel` | pandas' `storage_options` (fsspec's), in the pandas code.                                                             |
| `fsspec_storage_options`       | `json`, `excel`, `markdown`, `text`, `image`    | `fsspec.open`'s keyword arguments, in the code that reads with fsspec.                                                |
| `polars_delta_table_options`   | `delta`                                         | `scan_delta`'s `delta_table_options`.                                                                                 |
| `polars_delta_use_pyarrow`     | `delta`                                         | `scan_delta`'s `use_pyarrow`.                                                                                         |
| `polars_delta_pyarrow_options` | `delta`                                         | `scan_delta`'s `pyarrow_options`.                                                                                     |

Storage options that look like credentials are left out of the code. Without storage options, the code relies on the
environment's configuration and credentials.

## Working with the explorer from Python

```python
explorer = StorageExplorer("s3://my-bucket/data")
explorer
```

```python
explorer.folder_url  # the URL of the folder shown, e.g. to pass to polars or pandas
explorer.selected_urls  # the URLs of the selected items
```

## StorageExplorer options

| Option                              | Meaning                                                                                                                               |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `height="400px"`                    | Height of the tree and list; the preview panel adds its own space below. `"fill"`: as tall as the container, e.g. the launcher's tab. |
| `max_upload_bytes=10 * 1024 * 1024` | Largest file you can upload from your computer (default 10 MB; `None` for no limit).                                                  |
| `allow_download_to_local=True`      | "Download to local" in the right-click menu (`False`: left out, and refused by the kernel).                                           |
| `download_to_jupyterlab_path="."`   | Folder "Download to JupyterLab" copies into, e.g. `"~/Downloads"`; default: where it runs. `None`: left out.                          |
| `filesystems={...}`                 | Several named storages, as shown above.                                                                                               |
| `max_browser_items=20_000`          | Folders with more items are filtered, sorted and paged by the kernel, one page at a time, instead of the browser (`None`: never).     |
| `operations=[...]`                  | How files are moved, copied, deleted and downloaded, replacing `StorageExplorer.default_operations()`: e.g. `[MyOps(), *StorageExplorer.default_operations()]` for server-side copies of your own (see [operations.py](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/src/jupyter_storage_explorer/operations.py), and [filesystems](https://github.com/sugibuchi/jupyter-storage-explorer/tree/main/src/jupyter_storage_explorer/filesystems) for the defaults). |
| `query_settings=...`                | Where the data browser keeps its settings; see [Query data](#query-data).                                                             |
| `format_options={...}`              | Options for the formats (see [Format options](#format-options)).                                                                      |

## DataExplorer: browse a dataframe

`DataExplorer` opens the same data browser for a dataframe in your notebook: pandas, polars, PyArrow, DuckDB, Spark,
and the other libraries [narwhals](https://narwhals-dev.github.io/narwhals/) supports.

```python
import polars as pl
from jupyter_storage_explorer import DataExplorer, QuerySettings

DataExplorer(pl.scan_parquet("s3://my-bucket/lake/sales/*.parquet"))
DataExplorer(spark.table("sales"), mode="memory")  # read the first rows into memory
DataExplorer(orders_df, settings=QuerySettings(sort="date", descending=True))
```

![DataExplorer showing a Delta Lake table in a notebook](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/figs/data-explorer.png)

Lazy data starts **Live**, eager data **In memory**. Pass a function (`lambda: pl.scan_parquet(url)`) for **⟳** to
read the data again.

`explorer.result()` gives the data with the widget's filters, sort order and hidden columns applied, as a dataframe of
the same library (lazy data stays lazy), to continue your analysis in code:

```python
explorer = DataExplorer(pl.scan_parquet("sales/*.parquet"))
# ... filter and sort in the widget ...
explorer.result().group_by("region").agg(pl.col("amount").sum()).collect()
```

`QuerySettings` sets the filters, sort order, hidden columns and widths to start with. To keep settings made in the
widget, print them as text and paste them into your code:

```python
explorer = DataExplorer(orders_df)
print(explorer.settings.to_json())  # after filtering and sorting in the widget

DataExplorer(orders_df, settings=QuerySettings.from_json("""
{
    "filters": {"price": {"op": "range", "min": "10", "max": ""}},
    "sort": {"column": "date", "descending": true},
    "hidden": ["comment"],
    "widths": {}
}
"""))
```

### DataExplorer options

| Option                     | Meaning                                                                                                    |
|----------------------------|------------------------------------------------------------------------------------------------------------|
| `settings=QuerySettings()` | Filters, sort order, hidden columns and widths to start with (see above).                                  |
| `mode="auto"`              | Where queries run first: `"auto"`, `"live"` (lazy data only) or `"memory"`; switch in the widget.          |
| `max_live_rows=1000`       | Data up to this size is kept in memory; also the most rows a live query gives if the library cannot skip rows (e.g. Spark). |
| `max_memory_rows=100_000`  | The most rows read into memory.                                                                            |
| `title=...`                | Shown above the table (default: the dataframe's type).                                                     |
| `height="400px"`           | Height of the table area. `"fill"`: as tall as the container, e.g. a tab (not a notebook cell).            |
## Requirements

- Python 3.11 or later
- JupyterLab 4. The widgets also show in other Jupyter frontends, but dragging files from JupyterLab's file browser
  works only in JupyterLab.
- For Query data: a recent polars (tested with polars 2.0). `DataExplorer` works with any dataframe narwhals supports;
  with polars installed, data in memory is queried with polars, which is faster.

## Development

Building from source, the JupyterLab extension, releasing, and customizing the explorer's icons with CSS:
see [DEVELOPMENT.md](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md).
