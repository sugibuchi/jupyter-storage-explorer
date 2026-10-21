# jupyter-storage-explorer-abfs-support

Azure Data Lake Storage support for Storage Explorer, the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
Azure Data Lake Storage Gen2: folders moved in one step, copies within an account on the server, empty folders.

```bash
pip install "jupyter-storage-explorer[abfs]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[abfs-support]"  # the plugin only, with the libraries you have
```

Its libraries (`adlfs`, `azure-storage-file-datalake`) are not its dependencies, so that installing it never
changes those of a shared environment: the first command (or `jupyter-storage-explorer-abfs-support[full]`) installs them too.
Explorers use every plugin installed, unless their `plugin_options` disable it: `{"abfs-support": {"enabled": False}}`
(see [Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#plugins)).

## What it does

On storage accounts with a hierarchical namespace (Data Lake Storage Gen2), browsed with adlfs (`abfs://`), its
operation, `AzureDataLakeGen2Operation`, uses the Data Lake SDK with the adlfs filesystem's own account and credential:

- **Moves and renames** within an account in one request, however large the folder, never left half moved (adlfs alone
  copies then deletes file by file).
- **Copies** within an account by the storage itself (Copy Blob): no byte goes through the kernel. A file whose copy
  fails or is cancelled is deleted, never left partly copied.
- **Empty folders**, which adlfs alone cannot create.

Anything else (other storages, transfers between accounts, accounts without a hierarchical namespace) is left to the
explorer's other operations.

## Plugin options

`plugin_options={"abfs-support": {...}}` (in the launcher's tabs, `plugin_options()` in `launcher.py`):

```python
StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    plugin_options={"abfs-support": {"concurrency": 16}},
)
```

| Option        | Default | Meaning                                                                                                     |
|---------------|---------|-------------------------------------------------------------------------------------------------------------|
| `enabled`     | `True`  | Whether explorers use the plugin. `False`: not even imported.                                               |
| `priority`    | lowest  | Plugins of a higher priority come first: their operations are tried before the others'. Equal ones by key. |
| `concurrency` | `64`    | The most files copied at once on the server (`AzureDataLakeGen2Operation`'s `concurrency`).                 |

## AzureDataLakeGen2Operation

The plugin gives every explorer an `AzureDataLakeGen2Operation`, made with the plugin's options. To use it in one
explorer only, disable the plugin and give the operation yourself:

```python
from jupyter_storage_explorer_abfs_support import AzureDataLakeGen2Operation

StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    plugin_options={"abfs-support": {"enabled": False}},
    operations=[AzureDataLakeGen2Operation(concurrency=16)],
)
```

| Parameter     | Default | Meaning                                                                                                                         |
|---------------|---------|---------------------------------------------------------------------------------------------------------------------------------|
| `concurrency` | `64`    | The most files copied at once: a folder's files are copied a folder at a time, at most this many at once, its folders first. |
