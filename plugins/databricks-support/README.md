# jupyter-storage-explorer-databricks-support

Databricks support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
a Databricks workspace's files: Unity Catalog volumes, workspace files and legacy DBFS, through
[fsspec-databricks](https://github.com/sugibuchi/fsspec-databricks).

> **Experimental.** fsspec-databricks is experimental, and so is this plugin: it is not recommended for production
> use. Feedback is welcome, in this repository's
> [issues](https://github.com/sugibuchi/jupyter-storage-explorer/issues).

## Installation

```bash
pip install "jupyter-storage-explorer[databricks]"          # the plugin and its library
pip install "jupyter-storage-explorer[databricks-support]"  # the plugin only, with the library you have
```

The library is not the plugin's dependency, so that installing it never changes those of a shared environment. The
first command installs it, as does `jupyter-storage-explorer-databricks-support[full]`:

| Library             | Needed for                                    |
|---------------------|-----------------------------------------------|
| `fsspec-databricks` | Mandatory: the workspace's files, through fsspec |

The plugin is not in the explorer's `all` and `all-supports` extras: install it on purpose.

### Prerequisites

- fsspec-databricks reaches the workspace with the Databricks SDK's configuration: e.g. `DATABRICKS_HOST` and a
  credential, a profile of `~/.databrickscfg`, or the notebook's own on Databricks. See
  [Databricks unified authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth).

## What it does

Give the explorer fsspec-databricks' filesystem:

```python
from fsspec_databricks import DatabricksFileSystem
from jupyter_storage_explorer import StorageExplorer

StorageExplorer(filesystems={"Databricks": DatabricksFileSystem()})
```

URLs work too, e.g. `"dbfs://Volumes/main/sales"`, once `fsspec_databricks.use()` has made fsspec-databricks
fsspec's `dbfs` filesystem.

The plugin gives the files locations that name the workspace, by its host, besides their path, e.g.
`dbfs://Volumes/main/sales/raw/a.csv`:

- Two workspaces' files of the same path are told apart, also by "Paste" and the transfer policy's checks.
- Files copied in an explorer of another kernel are found again in the same workspace, even if this explorer did not
  show that storage, once `fsspec_databricks.use()` is called.

The folders of volumes, catalogs, schemas, repositories and users get icons of their own, as without the plugin.
pyspark-support's code reads the files as Databricks names them, `dbfs:/Volumes/...`.

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    filesystems={"Databricks": DatabricksFileSystem()},
    plugin_options={"databricks-support": {"priority": 10}},
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"databricks-support": {"enabled": False}}
```

| Option     | Default | Meaning                                                                                                 |
|------------|---------|---------------------------------------------------------------------------------------------------------|
| `enabled`  | `True`  | Whether explorers use the plugin. `False`: not even imported.                                           |
| `priority` | lowest  | Plugins of a higher priority come first: their mappers are tried before the others'. Equal ones by key. |
