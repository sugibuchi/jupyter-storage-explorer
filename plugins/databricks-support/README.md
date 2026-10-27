# jupyter-storage-explorer-databricks-support

Databricks support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
a Databricks workspace's files: Unity Catalog volumes, workspace files and legacy DBFS, through
[fsspec-databricks](https://github.com/sugibuchi/fsspec-databricks). It also adds Databricks Connect as an engine, to
read Delta Lake tables, Parquet, CSV and JSON Lines on Databricks compute.

> **Experimental.** fsspec-databricks is experimental, and so is this plugin: it is not recommended for production
> use. Feedback is welcome, in this repository's
> [issues](https://github.com/sugibuchi/jupyter-storage-explorer/issues).

## Installation

```bash
pip install "jupyter-storage-explorer[databricks]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[databricks-support]"  # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them, as does `jupyter-storage-explorer-databricks-support[full]`:

| Library              | Needed for                                       |
|----------------------|--------------------------------------------------|
| `fsspec-databricks`  | Mandatory: the workspace's files, through fsspec |
| `databricks-connect` | The Databricks Connect engine                    |

`databricks-connect` replaces `pyspark`: the two must not be installed together. Beside pyspark, install the plugin
alone. Databricks recommends a `databricks-connect` of your compute's Databricks Runtime version.

The plugin is not in the explorer's `all` and `all-supports` extras: install it on purpose. It installs
pyspark-support, whose actions the Databricks Connect engine shares.

### Prerequisites

- fsspec-databricks reaches the workspace with the Databricks SDK's configuration: e.g. `DATABRICKS_HOST` and a
  credential, or a profile of `~/.databrickscfg`. See
  [Databricks unified authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth).
- Databricks Connect also needs compute in that configuration: a cluster, e.g. `DATABRICKS_CLUSTER_ID`, or serverless.
  See [Databricks Connect](https://docs.databricks.com/aws/en/dev-tools/databricks-connect/python/).

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

## Databricks Connect

With `databricks-connect` installed, the engine "Databricks Connect" reads Delta Lake tables, Parquet, CSV and JSON
Lines on Databricks compute. Choose it from the status bar, as any engine.

- Files of fsspec-databricks' filesystem are read on that filesystem's workspace, with its credentials.
- Other files, e.g. on Azure or S3, are read with Databricks Connect's own configuration.
- The code it offers makes the session with `DatabricksSession.builder.getOrCreate()`: the workspace of your
  configuration, without the explorer's credentials.

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

## Engine options

The Databricks Connect engine's options are pyspark-support's, in `engine_options["databricks-connect"]`:

```python
StorageExplorer(
    filesystems={"Databricks": DatabricksFileSystem()},
    engine_options={
        "databricks-connect": {
            "*": {"session_options": {"spark.sql.ansi.enabled": "true"}},
            "csv": {"null_value": "NA"},
        },
    },
)
```

pyspark-support's
[Engine options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/pyspark-support/README.md#engine-options)
lists them. Two differ here:

- `session_options` are set on the session at run time, as Databricks Connect takes no others.
- `supported_protocols` defaults to `dbfs`, `s3a`, `abfss`, `abfs`, `wasbs`, `wasb` and `gs`. The cluster cannot read
  the kernel's local files, so they are neither viewed nor given code with Databricks Connect.
