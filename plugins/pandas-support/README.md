# jupyter-storage-explorer-pandas-support

pandas support for Storage Explorer, the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
pandas as an engine: the data browser on the first rows of Parquet, CSV, JSON Lines and Excel files, and code loading them.

```bash
pip install "jupyter-storage-explorer[pandas]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[pandas-support]"  # the plugin only, with the libraries you have
```

Its libraries (`pandas`, `pyarrow`, `openpyxl`) are not its dependencies, so that installing it never
changes those of a shared environment: the first command (or `jupyter-storage-explorer-pandas-support[full]`) installs them too.
Explorers use every plugin installed, unless their `plugins` argument names others
(see [StorageExplorer options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#storageexplorer-options)).
