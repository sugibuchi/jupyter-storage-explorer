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

Its option `concurrency` (default 64) is the most files copied at once on the server, e.g.
`plugin_options={"abfs-support": {"concurrency": 16}}`.
