# jupyter-storage-explorer-polars-support

Polars support for Storage Explorer, the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
Polars as an engine: the data browser on Delta Lake tables, Parquet, CSV, JSON Lines and Excel, and code loading them.

```bash
pip install "jupyter-storage-explorer[polars]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[polars-support]"  # the plugin only, with the libraries you have
```

Its libraries (`polars`, `deltalake`, `fastexcel`) are not its dependencies, so that installing it never
changes those of a shared environment: the first command (or `jupyter-storage-explorer-polars-support[full]`) installs them too.
Explorers use every plugin installed, unless their `plugin_options` disable it: `{"polars-support": {"enabled": False}}`
(see [Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#plugins)).
