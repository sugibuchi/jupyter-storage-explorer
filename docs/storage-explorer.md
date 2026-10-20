# StorageExplorer

`StorageExplorer` is the file explorer: browse storage, preview files, query tables, and upload, download, move and
edit files. For installation, see the [README](../README.md).

<img src="figs/storage-explorer.png" width="954" alt="StorageExplorer with a JSON Lines file open in the data browser">

- [Storages](#storages)
- [Using the explorer](#using-the-explorer)
- [Unsafe operations](#unsafe-operations)
- [Transfer policy](#transfer-policy)
- [Data browser and view tabs](#data-browser-and-view-tabs)
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
| `AzureDataLakeGen2Operation` | Azure Data Lake Storage Gen2 (hierarchical namespace) | Move folders in one step; copy within an account on the server, many files at once; create empty folders | `pip install "jupyter-storage-explorer[abfs]"` |

```python
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems.abfs import AzureDataLakeGen2Operation

StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    operations=[AzureDataLakeGen2Operation()],
)
```

To write your own, subclass `FileSystemOperations` (see [filesystems/operation.py](../src/jupyter_storage_explorer/filesystems/operation.py)).

## Using the explorer

### Browse

Click a folder in the tree to show it in the list; double-click it, or click ▸, to expand or collapse it. Double-click a
folder in the list to go into it; ↑ goes up, ⟳ refreshes, ◀ ▶ pages through the list. Ctrl+click (⌘+click) selects
several items. Hover over an item for its size, times, format and URL.

<img src="figs/using-browse.png" width="830" alt="Browsing a folder, with two items selected">

### Filter

Type in the field above the list to show names containing the text, or matching a regular expression with **.\***.
✕ or Esc clears; opening another folder clears it too.

<img src="figs/using-filter.png" width="562" alt="The list filtered with a regular expression">

### Open files

Double-click a file, or right-click → **Open in JupyterLab**, to open it in JupyterLab's own editor or viewer, as in its
file browser; **Save** writes it back to the storage. Files JupyterLab cannot show (Parquet, Excel, …) open in the
[preview](#preview). Needs the [launcher](../launcher/README.md) package; up to 20 MB per file. Notebooks open untrusted,
as JupyterLab opens notebooks from elsewhere: trust one (**Trust Notebook**) and save it, and it is trusted when you open
it again.

### Preview

The **Preview** link at the bottom right of the list (with nothing selected: the current folder, e.g. a Delta Lake
table), or right-click → **Preview**; **Preview as** chooses another format. Double-clicking a file previews it when
JupyterLab cannot [open it](#open-files), e.g. Parquet or Excel. Tables open in the [data browser](#data-browser-and-view-tabs). While
the panel is open, clicking a file previews it; `open_preview=True` opens it from the start. The same link, then
**Close preview**, or Esc, closes it.

<img src="figs/using-preview.png" width="562" alt="Preview in the status bar, and Preview as in the right-click menu of a Markdown file">

### Right-click

Open in JupyterLab (to edit), Preview, View in a new tab, Preview as, Python code to load the data (by library, e.g.
polars ▸ Load as LazyFrame), Copy URL (and on a local disk Copy path); Copy, Cut, Paste; Create a folder, Rename, Delete; Download to local or to JupyterLab; Properties, Add
bookmark. Preview, View in a new tab and Python code are offered for what has a format, e.g. not a plain folder. Local files' URLs are
`file:///` URLs, e.g. `file:///home/jovyan/x.csv`; Copy path gives the plain path, as Copy puts it on the clipboard.

<img src="figs/using-right-click.png" width="385" alt="The right-click menu of a JSON Lines file">

### Properties

A file's size, modification time and everything its storage tells about it; for folders and several items, the number
of files and folders, their total size, and the oldest and newest files.

<img src="figs/using-properties.png" width="640" alt="The properties of a folder">

### Bookmarks

Right-click a folder → **Add bookmark**. ☆ lists them; click one to open it, right-click it for Copy URL (Copy path
for a local folder) and Delete bookmark.

<img src="figs/using-bookmarks.png" width="308" alt="The bookmarks menu">

### Copy, cut and paste

Between storages and between explorers, also in other notebooks.

### Drag and drop

Drop files from JupyterLab's file browser or your computer to upload them; drag files onto a folder to move them, onto
another explorer of the same JupyterLab page (another tab or notebook) to copy them there, as Paste does, or onto
JupyterLab's file browser to download them (needs [the launcher](../launcher/README.md)). Drags from other browser tabs
or windows are refused.

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

## File transfer between file systems

Files are moved and copied within a storage by the storage itself where it can (a rename, a copy on the server); between
storages, the kernel copies them file by file, through a temporary file:

- A failed or cancelled copy leaves no partial file, and a move deletes each file only once its copy is complete.

When files are copied or dragged from one explorer to another, **the destination explorer reads them with a file
system of its own** for the source storage. If it has none for that storage, e.g. one in another kernel's memory or on another
machine's disk, the transfer is refused. Storages of kinds other than Azure, S3, Google Cloud Storage, SFTP, local disks
and in-memory ones are looked for only among the destination explorer's own storages.

![Two Storage Explorer tabs, one above the other: a CSV file dragged from a shared folder on the server's disk in the top tab into the scratch storage of the bottom tab, and pasted there](figs/file-transfer.gif)

For example, with a MinIO storage, `s3fs` with `endpoint_url="http://minio:9000"`, in the source explorer:

- If the destination explorer, in another notebook, has a storage of that endpoint, files dragged onto it are read
  with that storage.
- If not, but fsspec's configuration sets that endpoint for S3, they are read with the S3 storage fsspec opens.
- Otherwise they are refused.

## Transfer policy

`transfer_policy=[...]` limits where files may be copied or moved: within a storage (moves onto a folder, renames, copy
or cut and paste), between storages, to or from JupyterLab's file browser, and to or from your computer. The first rule
whose `src` and `dest` regular expressions match the whole URLs decides; without one, files go:

```python
StorageExplorer(filesystems={...}, transfer_policy=[
    {"rule": "allow", "src": r"abfs://lake@acct\.dfs\.core\.windows\.net/public/.*", "dest": ".*"},
    {"rule": "allow", "src": r"abfs://lake@.*", "dest": r"abfs://lake@.*"},  # within the lake
    {"rule": "deny", "src": r"abfs://lake@.*", "dest": ".*"},  # nothing else leaves the lake
])
```

URLs are those of "Copy URL" (`file:///...` for local files); files through JupyterLab's file browser are `jupyterlab://<absolute path>`, e.g.
`jupyterlab:///home/jovyan/x.csv`, and files on your computer `browser:///<name>`. A pattern left out matches any URL.
A folder is checked as one item, by its own URL. It prevents mistakes; it is not a security boundary. For the launcher's
tabs, use `transfer_policy()` in [its configuration](../launcher/README.md#configuration).

**Named groups** tie the two URLs together: `(?P<name>...)` in both patterns, and the rule matches only if each group
captures the same text in both. Both patterns must have the same group names. With `L` for
`acct\.dfs\.core\.windows\.net`:

| Files may move or be copied            | `src` and `dest` (an `allow` rule, before a broader `deny`)                                  |
|----------------------------------------|-----------------------------------------------------------------------------------------------|
| Within each container                  | `abfs://(?P<container>[^@/]+)@L/.*` in both                                                   |
| Within each project folder of `raw`    | `abfs://raw@L/(?P<project>[^/]+)/.*` in both                                                  |
| From `raw` to `curated`, same project  | `abfs://raw@L/(?P<project>[^/]+)/.*` → `abfs://curated@L/(?P<project>[^/]+)/.*`              |
| Within each user's folder              | `abfs://home@L/(?P<user>[^/]+)/.*` in both                                                    |

The `deny` after it has no groups, e.g. `{"rule": "deny", "src": r"abfs://[^@/]+@L/.*"}` for "not between containers".

## Data browser and view tabs

With [polars](https://pola.rs) installed (plus `deltalake` for Delta Lake, `fastexcel` for Excel), tables open in the
data browser: page, sort, filter and choose columns, on the data itself (**Live**) or on its first 100,000 rows
(**In memory**). It is `DataExplorer`'s browser; see [Using the data browser](data-explorer.md#using-the-data-browser).

With the [launcher](../launcher/README.md) package, the button at the right of the preview's title, or right-click →
**View in a new tab**, opens what the preview shows in a JupyterLab tab of its own: a table in the data browser, with
the same filters, sort and columns, and text, JSON, Markdown or an image as the preview panel shows them. Each tab is
a view of its own: open several to compare tables side by side. The tabs close with the explorer's tab or
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

| Format                                                       | Name         | Preview                       | Data browser | Load with                                           |
|--------------------------------------------------------------|--------------|-------------------------------|--------------|-----------------------------------------------------|
| Delta Lake tables                                            | `delta`      | First rows                    | ✓            | polars (with deltalake), PySpark (with delta-spark) |
| Parquet files, and folders of them (e.g. Spark, Hive output) | `parquet`    | First rows                    | ✓            | polars, pandas, PySpark                             |
| CSV, TSV                                                     | `csv`        | First rows                    | ✓            | polars, pandas, PySpark                             |
| JSON Lines                                                   | `json-lines` | First records                 | ✓            | polars, pandas, PySpark                             |
| JSON                                                         | `json`       | Collapsible tree              |              | Python, polars, pandas                              |
| Excel (`.xlsx`)                                              | `excel`      | First rows of the first sheet | ✓            | polars, pandas                                      |
| Markdown                                                     | `markdown`   | Rendered                      |              | Python                                              |
| Text, code, configuration (YAML, SQL, Python, …)             | `text`       | With syntax highlighting      |              | Python                                              |
| Images (PNG, JPEG, GIF, SVG, …)                              | `image`      | Shown                         |              | Pillow                                              |

Folders of Parquet files written by Spark or Hive, partitioned or not, are supported; folders written by other tools
may work, but are not guaranteed to.

Each format's view (the preview, the data browser) is the first installed library's, in the order above, and its code is
shown for every library, grouped by library in **Python code** (a support given for a library replaces the default one's). The name identifies the format in CSS (see
[Icons](../DEVELOPMENT.md#icons)) and in [Format options](#format-options). To handle a format with another
library, see [Another library for a format](../DEVELOPMENT.md#another-library-for-a-format).

## Format options

`format_options` gives the libraries' options, by library, then format name, or `"*"` for all formats (a format's
options override those for all):

```python
StorageExplorer(
    "s3://my-bucket/lake",
    format_options={
        "polars": {
            "*": {"storage_options": {"aws_region": "eu-west-1"}},
            "delta": {"use_pyarrow": True},
        },
        "pandas": {"*": {"storage_options": {"anon": False}}},
    },
)
```

| Library  | Option                   | Formats                                         | Meaning                                                                                                       |
|----------|--------------------------|-------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `polars` | `storage_options`        | `delta`, `parquet`, `csv`, `json-lines`         | polars' `storage_options` (object_store's names, not fsspec's), in the preview, the data browser and the code. |
| `polars` | `credential_provider`    | `delta`, `parquet`, `csv`, `json-lines`         | polars' `credential_provider`, in the preview and the data browser (not in the code).                          |
| `polars` | `fsspec_storage_options` | `excel`                                         | `fsspec.open`'s keyword arguments, in the code (which reads the file with fsspec).                             |
| `polars` | `delta_table_options`    | `delta`                                         | `scan_delta`'s `delta_table_options`.                                                                          |
| `polars` | `use_pyarrow`            | `delta`                                         | `scan_delta`'s `use_pyarrow`.                                                                                  |
| `polars` | `pyarrow_options`        | `delta`                                         | `scan_delta`'s `pyarrow_options`.                                                                              |
| `pandas` | `storage_options`        | `parquet`, `csv`, `json-lines`, `json`, `excel` | pandas' `storage_options` (fsspec's), in the code.                                                             |
| `fsspec` | `storage_options`        | `json`, `markdown`, `text`                      | `fsspec.open`'s keyword arguments, in the code.                                                                |
| `pillow` | `storage_options`        | `image`                                         | `fsspec.open`'s keyword arguments, in the code (which reads the file with fsspec).                             |

Options that look like credentials are left out of the code. A library, format or option name that no support takes is
an error.

Options that depend on where the data is, e.g. one key per Azure storage account, are given by a function of the item's
location instead of a dict. It is called each time a file is viewed or its code shown:

```python
keys = {"sales": "...", "finance": "..."}

StorageExplorer(
    filesystems={"Sales": "abfs://lake@sales.dfs.core.windows.net", "Finance": "abfs://lake@finance.dfs.core.windows.net"},
    format_options={
        "polars": {"*": lambda location: {"storage_options": {"account_key": keys[location.account_name]}}},
    },
)
```

The location is a `jupyter_storage_explorer.Location`: `AbfsLocation` (`account_name`, `container_name`, `path`),
`S3Location` (`bucket`, `key`), `LocalLocation`, ... (`jupyter_storage_explorer.filesystems`). In the launcher's
`format_options()`, a later layer's options still override an earlier layer's option by option, functions or not.

## Working with the explorer from Python

```python
explorer = StorageExplorer("s3://my-bucket/data")
explorer
```

```python
explorer.folder_url  # the URL of the folder shown, e.g. to pass to polars or pandas
explorer.selected_urls  # the URLs of the selected items
explorer.folder_location  # where the folder shown is: its .url, and a local folder's .path
explorer.selected_locations  # the same for the selected items
explorer.query_result()  # the table in the data browser, with its filters; None if none
```

Locations (`jupyter_storage_explorer.Location`) are immutable and compare equal when they name the same item: an
`S3Location` has the bucket, key and endpoint, an `AbfsLocation` the account, container and path, a `LocalLocation` the
plain path (`.os_path` in your system's form) and its machine. `.to_json()` and `Location.from_json()` keep them.

`on_change(f)` calls `f(explorer)` when the folder shown or the selection changes, and `on_query_change(f)` when
`query_result()` does: another table opened in the preview panel (or none), other filters, sort or columns, or the data
read again. The functions run as the kernel handles the widget's messages, so what they print goes to no cell: display
into an `ipywidgets.Output`. Keep them quick: the widget waits for them. `remove=True` stops calling one.

For example, a chart of the CSV file you click, which follows the filters you set in the data browser. Some CSV files
in a cloud storage first:

```python
import datetime as dt
import random

import fsspec
import polars as pl

folder = "s3://my-bucket/demo/sales"  # any storage you can write to
days = pl.date_range(dt.date(2026, 1, 1), dt.date(2026, 6, 30), eager=True)
for region in ["north", "south", "east", "west"]:
    sales = pl.DataFrame(
        {
            "date": days,
            "channel": random.choices(["online", "retail", "wholesale"], k=len(days)),
            "amount": [random.randint(50, 500) for _ in days],
        }
    )
    with fsspec.open(f"{folder}/{region}.csv", "w") as f:
        sales.write_csv(f)
```

An explorer of them, its preview panel open, so that clicking a file opens it in the data browser:

```python
from jupyter_storage_explorer import StorageExplorer

explorer = StorageExplorer(folder, open_preview=True)
explorer
```

And the chart, in a cell of its own:

```python
import ipywidgets
import matplotlib.pyplot as plt

chart = ipywidgets.Output()


def draw(explorer):
    with chart:
        chart.clear_output(wait=True)
        result = explorer.query_result()
        if result is None:
            return  # no table in the preview panel
        daily = result.group_by("date").agg(pl.col("amount").sum()).sort("date").collect()
        plt.figure(figsize=(8, 3))
        plt.plot(daily["date"], daily["amount"])
        plt.show()


explorer.on_query_change(draw)
chart
```

Filter by channel in the data browser, and the chart shows that channel's sales. Without the data browser,
`on_change` and `selected_urls` give the files themselves, e.g. `pl.read_csv(url)` for each one selected.

## StorageExplorer options

| Option                              | Meaning                                                                                                                               |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `height="400px"`                    | Height of the tree and list; the preview panel adds its own space below. `"fill"`: as tall as the container, e.g. the launcher's tab. |
| `open_preview=True`                 | Start with the preview panel open, so that clicking a file previews it (default: closed).                                             |
| `max_upload_bytes=10 * 1024 * 1024` | Largest file you can upload from your computer (default 10 MB; `None` for no limit).                                                  |
| `download_to_jupyterlab_path="."`   | Folder "Download to JupyterLab" copies into, e.g. `"~/Downloads"`; default: where it runs. To refuse downloads, use `transfer_policy`. |
| `filesystems={...}`                 | Several named storages; see [Several storages in one explorer](#several-storages-in-one-explorer).                                    |
| `max_browser_items=20_000`          | Folders with more items are filtered, sorted and paged by the kernel, one page at a time, instead of the browser (`None`: never).     |
| `fetch_rows=...`                    | How the data browser reads pages; see [Reading pages](#reading-pages).                                                                |
| `view_limits=ViewLimits(...)`       | How much views read and show (`formats.ViewLimits`): `max_bytes`, `max_display_rows` (also the data browser's page size), `max_whole_file_bytes`, `max_live_rows`, `max_memory_rows`. |
| `operations=[...]`                  | File operation extensions, tried before the defaults; see [File operation extensions](#file-operation-extensions).                   |
| `filesystem_mappers=[...]`          | The locations of storages' paths, by which they are told apart, tried before the defaults; see [File transfer](#file-transfer-between-file-systems). |
| `transfer_policy=[...]`             | Rules for transfers of files between storages; see [Transfer policy](#transfer-policy).                                               |
| `states="states.json"`              | Where bookmarks and the data browser's settings are kept (a path or an `ExplorerStates`); see [Remembered states](#remembered-states). |
| `formats=[...]`                     | The formats files are detected as, replacing the defaults (`default_formats()`).                                                      |
| `supports=[...]`                    | Libraries of your own for formats, tried before the defaults; see [Another library for a format](../DEVELOPMENT.md#another-library-for-a-format). |
| `format_options={...}`              | The libraries' options (see [Format options](#format-options)).                                                                       |
