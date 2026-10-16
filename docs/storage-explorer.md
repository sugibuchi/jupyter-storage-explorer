# StorageExplorer

`StorageExplorer` is the file explorer: browse storage, preview files, query tables, and upload, download, move and
edit files. For installation, see the [README](../README.md).

<img src="figs/storage-explorer.png" width="954" alt="StorageExplorer with a JSON Lines file open in the data browser">

- [Storages](#storages)
- [Using the explorer](#using-the-explorer)
- [Unsafe operations](#unsafe-operations)
- [Transfer policy](#transfer-policy)
- [Query data](#query-data)
- [Remembered states](#remembered-states)
- [Supported formats](#supported-formats)
- [Format options](#format-options)
- [Working with the explorer from Python](#working-with-the-explorer-from-python)
- [StorageExplorer options](#storageexplorer-options)

## Storages

Give the address of the folder to open; options after it go to the storage package, e.g. credentials:

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer()  # the current folder
StorageExplorer("abfs://lake@myaccount.dfs.core.windows.net/raw")  # Azure Data Lake
StorageExplorer("s3://my-bucket/data", profile="analytics")  # Amazon S3, with options
StorageExplorer("gs://my-bucket", token="google_default")  # Google Cloud
```

| Storage                        | Package    | Address                                              |
|--------------------------------|------------|------------------------------------------------------|
| Amazon S3                      | `s3fs`     | `s3://bucket/path`                                   |
| Azure Data Lake / Blob Storage | `adlfs`    | `abfs://container@account.dfs.core.windows.net/path` |
| Google Cloud Storage           | `gcsfs`    | `gs://bucket/path`                                   |
| Local disk, in-memory          | (included) | `/path`, `memory://`                                 |

### Several storages in one explorer

Name each storage, and switch between them with the drop-down above the tree:

```python
StorageExplorer(
    filesystems={
        "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
        "Raw files (S3)": "s3://my-bucket/raw",
        "Local": "/home/me/data",
    },
)
```

### File operation extensions

The explorer moves, copies, deletes and downloads files with fsspec's standard API, which works on any storage but not
always efficiently: e.g. moving a folder copies and deletes each file in it. Extensions add implementations of some
operations optimized for a particular storage. Pass them as `operations=[...]`.

| Extension                    | Storage                                               | Operations                                         | Install                                      |
|------------------------------|-------------------------------------------------------|----------------------------------------------------|----------------------------------------------|
| `AzureDataLakeGen2Operation` | Azure Data Lake Storage Gen2 (hierarchical namespace) | Move folders in one step; create empty folders     | `pip install "jupyter-storage-explorer[abfs]"` |

```python
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems.abfs import AzureDataLakeGen2Operation

StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    operations=[AzureDataLakeGen2Operation()],
)
```

To write your own, subclass `FileSystemOperations` (see [operations.py](../src/jupyter_storage_explorer/operations.py)).

## Using the explorer

### Browse

Click folders in the tree or list; ↑ goes up, ⟳ refreshes, ◀ ▶ pages through the list. Ctrl+click (⌘+click) selects
several items. Hover over an item for its size, times, format and URL.

<img src="figs/using-browse.png" width="830" alt="Browsing a folder, with two items selected">

### Filter

Type in the field above the list to show names containing the text, or matching a regular expression with **.\***.
✕ or Esc clears; opening another folder clears it too.

<img src="figs/using-filter.png" width="562" alt="The list filtered with a regular expression">

### Open files

Double-click a file, or right-click → **Open in JupyterLab**, to open it in JupyterLab's own editor or viewer, as in its
file browser; **Save** writes it back to the storage. Files JupyterLab cannot show (Parquet, Excel, …) open in the
[preview](#preview). Needs the [launcher](../launcher/README.md) package; up to 20 MB per file.

### Preview

**Preview** below the list (with nothing selected: the current folder, e.g. a Delta Lake table), or right-click →
**Preview**; **Preview as** chooses another format. Double-clicking a file previews it when JupyterLab cannot
[open it](#open-files), e.g. Parquet or Excel. Tables open in the [data browser](#query-data). While the panel is
open, clicking a file previews it. **Close preview** below the list, or Esc, closes it.

<img src="figs/using-preview.png" width="562" alt="Preview in the status bar, and Preview as in the right-click menu of a Markdown file">

### Right-click

Open in JupyterLab (to edit), Preview as, Query data in new tab, Python code to load the data, Copy URL; Copy, Cut,
Paste; Create a folder, Rename, Delete; Download to local or to JupyterLab; Properties, Add bookmark. Preview and Python
code are offered for what has a format, e.g. not a plain folder.

<img src="figs/using-right-click.png" width="384" alt="The right-click menu of a JSON Lines file">

### Properties

A file's size, modification time and everything its storage tells about it; for folders and several items, the number
of files and folders, their total size, and the oldest and newest files.

<img src="figs/using-properties.png" width="640" alt="The properties of a folder">

### Bookmarks

Right-click a folder → **Add bookmark**. ☆ lists them; click one to open it, right-click it for Copy URL and Delete
bookmark.

<img src="figs/using-bookmarks.png" width="245" alt="The bookmarks menu">

### Copy, cut and paste

Between storages and between explorers, also in other notebooks.

### Drag and drop

Drop files from JupyterLab's file browser or your computer to upload them; drag files onto a folder to move them, or
onto JupyterLab's file browser to download them (needs [the launcher](../launcher/README.md)).

### Background operations

Moving, renaming, deleting, pasting and downloading to JupyterLab run in the background, with progress and **Cancel** above the
status bar.

## Unsafe operations

Folder operations need **Unsafe mode**, turned on with the slider at the right of the toolbar, for one operation:

<img src="figs/unsafe-mode.png" width="405" alt="The Unsafe mode slider, on, at the right of the toolbar">

| Operation              | How                                                                                          |
|------------------------|----------------------------------------------------------------------------------------------|
| Move folders           | Drag a folder onto another folder, or right-click → **Cut**, then **Move here** on a folder. |
| Copy and paste folders | Right-click → **Copy**, then **Paste** on a folder.                                          |
| Rename folders         | Right-click → **Rename** (on most storages, a move of everything in it).                     |
| Delete folders         | Right-click → **Delete** (with everything in it).                                            |

## Transfer policy

`transfer_policy=[...]` limits where files may be transferred: between storages, to or from JupyterLab's file browser,
and to or from your computer (not within a storage). The first rule whose `src` and `dest` regular expressions match
the whole URLs decides; without one, files go:

```python
StorageExplorer(filesystems={...}, transfer_policy=[
    {"rule": "allow", "src": r"abfs://lake@acct\.dfs\.core\.windows\.net/public/.*", "dest": ".*"},
    {"rule": "deny", "src": r"abfs://lake@.*", "dest": ".*"},  # nothing else leaves the lake
])
```

URLs are those of "Copy URL"; files through JupyterLab's file browser are `jupyterlab://<absolute path>`, e.g.
`jupyterlab:///home/jovyan/x.csv`, and files on your computer `browser:///<name>`. A pattern left out matches any URL.
It prevents mistakes; it is not a security boundary. For the launcher's tabs, use `transfer_policy()` in
[its configuration](../launcher/README.md#configuration).

## Query data

With [polars](https://pola.rs) installed (plus `deltalake` for Delta Lake, `fastexcel` for Excel), tables open in the
data browser: page, sort, filter and choose columns, on the data itself (**Live**) or on its first 100,000 rows
(**In memory**). It is `DataExplorer`'s browser; see [Using the data browser](data-explorer.md#using-the-data-browser).

With the [launcher](../launcher/README.md) package, the button at the right of the preview's title, or right-click →
**Query data in new tab**, opens the data browser in a JupyterLab tab of its own, with the same filters, sort and columns.
Each tab is a query of its own: open several to compare tables side by side. The tabs close with the explorer's tab or
notebook, or when its kernel restarts, and are not reopened after a page reload.

polars reads the data with the credentials in the environment, not the explorer's options; see
[Format options](#format-options) for its own.

### Reading pages

`fetch_rows=` customizes how live queries read each page of rows. Tables can be read by different libraries, so check
the library of the data, handle those you want to, and return `None` for the others to read them the default way:

```python
import narwhals as nw


def streaming_pages(lf, offset, length):
    if lf.implementation.is_polars():
        page = lf.to_native().slice(offset, length).collect(engine="streaming")
        return nw.from_native(page)
    return None  # other libraries: the default


StorageExplorer("s3://my-bucket/lake", fetch_rows=streaming_pages)
```

## Remembered states

Bookmarks and the data browser's settings are shared by the explorers in the kernel. To keep them in a file, shared
with other kernels and [the launcher](../launcher/README.md)'s tabs, give its path, or an `ExplorerStates` for other
options:

```python
from jupyter_storage_explorer import ExplorerStates, StorageExplorer

StorageExplorer("s3://my-bucket/data", states="~/.jupyter/storage-explorer/states.json")  # the launcher's file
StorageExplorer("s3://my-bucket/data", states=ExplorerStates("states.json", max_queries=50))
```

## Supported formats

| Format                                                       | Name         | Preview                       | Query data | Load with                                           |
|--------------------------------------------------------------|--------------|-------------------------------|------------|-----------------------------------------------------|
| Delta Lake tables                                            | `delta`      | First rows                    | ✓          | polars (with deltalake), PySpark (with delta-spark) |
| Parquet files, and folders of them (e.g. Spark, Hive output) | `parquet`    | First rows                    | ✓          | polars, pandas, PySpark                             |
| CSV, TSV                                                     | `csv`        | First rows                    | ✓          | polars, pandas, PySpark                             |
| JSON Lines                                                   | `json-lines` | First records                 | ✓          | polars, pandas, PySpark                             |
| JSON                                                         | `json`       | Collapsible tree              |            | Python, polars, pandas                              |
| Excel (`.xlsx`)                                              | `excel`      | First rows of the first sheet | ✓          | polars, pandas                                      |
| Markdown                                                     | `markdown`   | Rendered                      |            | Python                                              |
| Text, code, configuration (YAML, SQL, Python, …)             | `text`       | With syntax highlighting      |            | Python                                              |
| Images (PNG, JPEG, GIF, SVG, …)                              | `image`      | Shown                         |            | Pillow                                              |

The name identifies the format in CSS (see [Customizing icons](../DEVELOPMENT.md#customizing-icons)).

## Format options

`format_options` is one dictionary for all formats; each uses the options it takes, named after their library (and
format):

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

Options that look like credentials are left out of the code.

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
| `download_to_jupyterlab_path="."`   | Folder "Download to JupyterLab" copies into, e.g. `"~/Downloads"`; default: where it runs. To refuse downloads, use `transfer_policy`. |
| `filesystems={...}`                 | Several named storages; see [Several storages in one explorer](#several-storages-in-one-explorer).                                    |
| `max_browser_items=20_000`          | Folders with more items are filtered, sorted and paged by the kernel, one page at a time, instead of the browser (`None`: never).     |
| `fetch_rows=...`                    | How the data browser reads pages; see [Reading pages](#reading-pages).                                                                |
| `operations=[...]`                  | File operation extensions, tried before the defaults; see [File operation extensions](#file-operation-extensions).                   |
| `transfer_policy=[...]`             | Rules for transfers of files between storages; see [Transfer policy](#transfer-policy).                                               |
| `states="states.json"`              | Where bookmarks and the data browser's settings are kept (a path or an `ExplorerStates`); see [Remembered states](#remembered-states). |
| `format_options={...}`              | Options for the formats (see [Format options](#format-options)).                                                                      |
