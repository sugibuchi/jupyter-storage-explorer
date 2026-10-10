# Jupyter Storage Explorer

A file explorer for cloud storage and data lakes, right inside your Jupyter notebook, in the spirit of Azure Storage
Explorer.

Browse Amazon S3, Azure Data Lake / Blob Storage, Google Cloud Storage, local disks and more; preview Parquet files,
Delta Lake tables, CSV, Excel, JSON and other formats; get ready-to-run code that loads the data into your notebook; and
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

## Supported formats

| Format                                                       | Preview                       | Load with               |
|--------------------------------------------------------------|-------------------------------|-------------------------|
| Delta Lake tables                                            | First rows                    | polars (with deltalake) |
| Parquet files, and folders of them (e.g. Spark, Hive output) | First rows                    | polars, pandas          |
| CSV, TSV                                                     | First rows                    | polars, pandas          |
| JSON Lines                                                   | First records                 | polars, pandas          |
| JSON                                                         | Collapsible tree              | Python, polars, pandas  |
| Excel (`.xlsx`)                                              | First rows of the first sheet | polars, pandas          |
| Markdown                                                     | Rendered                      | Python                  |
| Text, code, configuration (YAML, SQL, Python, …)             | With syntax highlighting      | Python                  |
| Images (PNG, JPEG, GIF, SVG, …)                              | Shown                         | Pillow                  |

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

## Requirements

- Python 3.11 or later
- JupyterLab 4. The explorer is a notebook widget, so it also shows in other Jupyter frontends, but dragging files from
  JupyterLab's file browser works only in JupyterLab.
