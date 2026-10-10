# Jupyter Storage Explorer

A file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the spirit of Azure Storage
Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; sort and filter tables; get ready-to-run code that loads the data into your notebook; and
upload, download, move and edit files without leaving JupyterLab.

## Installation

```bash
pip install jupyter-storage-explorer
```

Install the package for your storage too:

| Storage                        | Package    | Address                 |
|--------------------------------|------------|-------------------------|
| Amazon S3                      | `s3fs`     | `s3://bucket/path`      |
| Azure Data Lake / Blob Storage | `adlfs`    | `abfs://container/path` |
| Google Cloud Storage           | `gcsfs`    | `gs://bucket/path`      |
| Local disk, in-memory          | (included) | `/path`, `memory://`    |

Previewing data files needs a data library, e.g. `pip install polars deltalake`. If one is missing, the preview tells
you what to install.

## Quick start

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("s3://my-bucket/data")
```

The explorer appears as the cell's output. Other examples:

```python
StorageExplorer()  # the current folder
StorageExplorer("abfs://lake/raw", account_name="myaccount")  # Azure, with options
StorageExplorer("gs://my-bucket", token="google_default")  # Google Cloud
```

Options after the address (like `account_name` above) are passed to the storage package, for example to choose an
account or credentials.

### Several storages in one explorer

Give each storage a name; a drop-down on the left of the address bar switches between them, and each one remembers the
folder you were in.

```python
StorageExplorer(
    filesystems={
        "Data lake": "abfs://lake",
        "Raw files (S3)": "s3://my-bucket/raw",
        "Local": "/home/me/data",
    },
)
```

## Using the explorer

**Browse**

- Click a folder in the tree on the left to list it; double-click a folder in the list to open it.
- Click a folder name in the address bar at the top to go back to it; ↑ goes to the parent folder and ⟳ refreshes.
- Click to select, Ctrl+click (⌘+click on a Mac) to select several items; click a column header to sort.

**Preview**

- Double-click a file to preview it in a panel below the list. While the panel is open, clicking another file previews
  that one. Esc or ✕ closes it.
- **Preview** in the toolbar previews the selected item, or, with nothing selected, the folder you are in — for example
  a Delta Lake table you opened from the tree. The button shows the format it will use, like *Preview (Delta Lake
  table)*.
- Drag the bar above the panel to share the space between the list and the preview; drag the bar at the bottom to make
  the whole explorer taller or shorter.
- Tables (Delta Lake, Parquet, CSV, JSON Lines, Excel) open in the data browser instead when polars is installed: the
  button reads *Query data (…)*. See [Query data](#query-data).

**Right-click menu**

- **Preview** / **Preview as ▸**: show a file in another way, e.g. a JSON file as text.
- **Open**: open a folder.
- **Edit**: edit a text file, then **Save** or **Cancel**.
- **Python code ▸ Load with polars / pandas / …**: the code to load the data into your notebook, with the install
  command if a package is missing. Copy it into a cell.
- **Download**: save the selected files to your computer.
- **Copy path** / **Copy URL**: copy the location of the selected items.

**Drag and drop**

- **Upload**: drop files from JupyterLab's file browser or from your computer onto the list (into the folder shown) or
  onto a folder.
- **Move**: drag files in the list onto a folder in the list or the tree.
- You are asked to confirm, and asked what to do if files with the same names already exist (**Overwrite**, **Skip
  existing** or **Cancel**).

## Query data

With [polars](https://pola.rs) installed (plus `deltalake` for Delta Lake tables and `fastexcel` for Excel), tables open
in a data browser rather than a fixed preview of the first rows. Only the rows on screen are read.

- **Page** through the rows with ◀ and ▶, 100 rows at a time.
- **Sort**: click a column name; click again for descending, a third time to stop sorting.
- **Filter**: click the funnel next to a column name. The choices depend on the column's type: *Null / empty*, equals,
  contains, regular expression (text, optionally ignoring case), greater / less than (numbers, dates and times). Dates
  are entered as `2025-01-31` or `2025-01-31 12:00`.
- Active filters are listed next to **Select columns**; click one to change it, or × to remove it.
- **Select columns** hides and shows columns.
- **Resize** a column by dragging the right edge of its header; double-click the edge to go back to automatic widths.
- **Reset** removes all filters and shows all columns again (sorting and widths are kept).

Filters, sorting, hidden columns and widths are remembered per table, so reopening it shows it as you left it. By default
they are remembered until the kernel restarts; to keep them for good, store them in a file:

```python
from jupyter_storage_explorer.query import QuerySettingsStore

StorageExplorer("s3://my-bucket/data", query_settings=QuerySettingsStore("query-settings.json"))
```

## Supported formats

| Format                                                       | Preview                       | Query data | Load with               |
|--------------------------------------------------------------|-------------------------------|------------|-------------------------|
| Delta Lake tables                                            | First rows                    | ✓          | polars (with deltalake) |
| Parquet files, and folders of them (e.g. Spark, Hive output) | First rows                    | ✓          | polars, pandas          |
| CSV, TSV                                                     | First rows                    | ✓          | polars, pandas          |
| JSON Lines                                                   | First records                 | ✓          | polars, pandas          |
| JSON                                                         | Collapsible tree              |            | Python, polars, pandas  |
| Excel (`.xlsx`)                                              | First rows of the first sheet | ✓          | polars, pandas          |
| Markdown                                                     | Rendered                      |            | Python                  |
| Text, code, configuration (YAML, SQL, Python, …)             | With syntax highlighting      |            | Python                  |
| Images (PNG, JPEG, GIF, SVG, …)                              | Shown                         |            | Pillow                  |

## Working with the explorer from Python

```python
explorer = StorageExplorer("s3://my-bucket/data")
explorer
```

```python
explorer.selected_urls  # locations of the selected items, e.g. to pass to pandas
explorer.current_dir  # the folder shown
explorer.filesystem = "Local"  # switch storage (with several filesystems)
```

## Options

| Option                              | Meaning                                                                              |
|-------------------------------------|--------------------------------------------------------------------------------------|
| `height="400px"`                    | Height of the tree and list; the preview panel adds its own space below.             |
| `max_upload_bytes=10 * 1024 * 1024` | Largest file you can upload from your computer (default 10 MB; `None` for no limit). |
| `filesystems={...}`                 | Several named storages, as shown above.                                              |
| `query_settings=...`                | Where the data browser keeps its settings; see [Query data](#query-data).            |

## Customizing icons

Rows in the explorer carry attributes you can style with CSS:

- **Folders** (tree and list): `data-depth`, their level below the top folder: `0` for the top folder itself, `1` for
  the folders in it, and so on.
- **Files** (list): `data-file-format`, the format name in lower case with `-` for spaces: `parquet`, `csv`, `json`,
  `json-lines`, `excel-workbook`, `markdown`, `text`, `image`. Files of no known format have none.

Run CSS in a notebook cell, before or after the explorer. This example shows the top folder as a grey container,
the folders in it in blue-grey and deeper folders in yellow, and gives data files their own icons:

```python
from IPython.display import HTML

HTML("""<style>
/* Folders: draw an SVG shape in a colour, both chosen per depth below */
.jse-browser [data-depth] .jse-icon { font-size: 0; }
.jse-browser [data-depth] .jse-icon::before {
  content: ""; display: inline-block; width: 16px; height: 13px; vertical-align: -2px;
  background: var(--folder-color);
  -webkit-mask: var(--folder-shape) no-repeat center / contain;
          mask: var(--folder-shape) no-repeat center / contain;
}
.jse-browser [data-depth] {
  --folder-color: #eab308;
  --folder-shape: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 13'%3E%3Cpath d='M0 1.5A1.5 1.5 0 0 1 1.5 0h4l1.5 2h7.5A1.5 1.5 0 0 1 16 3.5v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 11.5z'/%3E%3C/svg%3E");
}
.jse-browser [data-depth="1"] { --folder-color: #64748b; }
.jse-browser [data-depth="0"] {
  --folder-color: #6b7280;
  --folder-shape: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 13'%3E%3Cpath fill-rule='evenodd' d='M1 0.5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1zM3 3v7h1.3V3zM6 3v7h1.3V3zM9 3v7h1.3V3zM12 3v7h1.3V3z'/%3E%3C/svg%3E");
}

/* Files: a different emoji per format */
.jse-browser [data-file-format] .jse-icon { font-size: 0; }
.jse-browser [data-file-format] .jse-icon::before { font-size: 14px; content: "📄"; }
.jse-browser [data-file-format="csv"] .jse-icon::before,
.jse-browser [data-file-format="excel-workbook"] .jse-icon::before { content: "📊"; }
.jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
.jse-browser [data-file-format="image"] .jse-icon::before { content: "🖼️"; }
.jse-browser [data-file-format="markdown"] .jse-icon::before { content: "📝"; }
</style>""")
```

`HTML(...)` must be the last line of the cell (or use `display(HTML(...))`). The style lasts until the page is reloaded.
To apply it to every notebook, save the CSS (without `<style>`) to `~/.jupyter/custom/custom.css` and start JupyterLab
with `jupyter lab --LabApp.custom_css=True`.

## Requirements

- Python 3.11 or later
- JupyterLab 4. The explorer is a notebook widget, so it also shows in other Jupyter frontends, but dragging files from
  JupyterLab's file browser works only in JupyterLab.
