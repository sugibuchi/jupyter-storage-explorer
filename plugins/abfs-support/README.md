# jupyter-storage-explorer-abfs-support

Azure Data Lake Storage support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
Azure Data Lake Storage Gen2: folders moved and deleted in one step, copies within an account on the server, empty
folders.

## Installation

```bash
pip install "jupyter-storage-explorer[abfs]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[abfs-support]"  # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them, as does `jupyter-storage-explorer-abfs-support[full]`:

| Library                       | Needed for                                              |
|-------------------------------|---------------------------------------------------------|
| `adlfs`                       | Mandatory: the `abfs://` storage the plugin works on    |
| `azure-storage-file-datalake` | Mandatory: the Data Lake SDK doing the plugin's work    |

Without either, the explorer's default operations do everything, file by file.

### Prerequisites

- The storage account has a hierarchical namespace (Data Lake Storage Gen2). On other accounts, the plugin only
  speeds up folder deletions.
- The plugin uses the explorer's adlfs storage with its own account and credential: it needs no settings of its own.

## What it does

On storage accounts with a hierarchical namespace (Data Lake Storage Gen2), browsed with adlfs (`abfs://`), its
operation, `AzureDataLakeGen2Operation`, uses the Data Lake SDK with the adlfs filesystem's own account and credential:

- **Moves and renames** within an account in one request, however large the folder, never left half moved (adlfs alone
  copies then deletes file by file).
- **Folder deletions** in one request, however large the folder, never left half deleted. adlfs alone deletes file by
  file.
- **Copies** within an account by the storage itself (Copy Blob): no byte goes through the kernel. A file whose copy
  fails or is cancelled is deleted, never left partly copied.
- **Empty folders**, which adlfs alone cannot create.

On accounts without a hierarchical namespace, it deletes folders in batches of files. Their progress moves batch by
batch, and Cancel stops them between two batches. adlfs alone checks every file one by one before deleting any.

Anything else is left to the explorer's other operations:

- other storages;
- transfers between accounts;
- moves, copies and new folders on accounts without a hierarchical namespace.

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    plugin_options={"abfs-support": {"concurrency": 16}},
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"abfs-support": {"concurrency": 16}}
```

<!-- options: jupyter_storage_explorer.StorageExplorerPluginOptions, jupyter_storage_explorer_abfs_support.AbfsSupportOptions -->
| Option        | Default | Meaning                                                                                                                         |
|---------------|---------|---------------------------------------------------------------------------------------------------------------------------------|
| `enabled`     | `True`  | Whether explorers use the plugin. `False`: not even imported.                                                                   |
| `priority`    | lowest  | Plugins of a higher priority come first: their actions, operations and mappers are tried before the others'. Equal ones by key. |
| `concurrency` | `64`    | The most files copied at once on the server (`AzureDataLakeGen2Operation`'s `concurrency`).                                     |

## AzureDataLakeGen2Operation

The plugin gives every explorer an `AzureDataLakeGen2Operation`, made with the plugin's options. To use it in one
explorer only, disable the plugin and give the operation yourself:

```python
from jupyter_storage_explorer_abfs_support import AzureDataLakeGen2Operation

StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    plugin_options={"abfs-support": {"enabled": False}},
    filesystem_operations=[AzureDataLakeGen2Operation(concurrency=16)],
)
```

| Parameter      | Default | Meaning                                                                                                                      |
|----------------|---------|------------------------------------------------------------------------------------------------------------------------------|
| `concurrency`  | `64`    | The most files copied at once: a folder's files are copied a folder at a time, at most this many at once, its folders first. |
| `delete_batch` | `256`   | The files deleted at once on accounts without a hierarchical namespace.                                                      |
