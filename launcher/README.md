# Jupyter Storage Explorer launcher

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer-launcher?color=blue)](https://pypi.org/project/jupyter-storage-explorer-launcher/)

Adds **Storage Explorer** to JupyterLab's launcher (section *Other*) and command palette. It opens
[Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/README.md) in its own tab, on
the folder JupyterLab's file browser shows.

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

It also adds a **side panel**, a narrow explorer next to your notebooks:

- Open it with the Storage Explorer icon in the left side bar.
- The same storages as the tab; a folder's list, without the tree or the preview panel.
- Files you view (**View**, a double-click) open in new tabs.
- The filter button, left of ⚙, shows the filter.

<img src="https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/side-panel.png" width="867" alt="The side panel in JupyterLab's left side bar, a Parquet file selected, beside the tab its View button opened in the data browser">


It also integrates every Storage Explorer, in its tab or in a notebook, with JupyterLab:

- **Drag and drop**: drag files onto JupyterLab's file browser to download them there.
- **Open files in a tab**: double-click a file to open it in JupyterLab's own editor or viewer; **Save** writes it back
  to the storage.
- **View in a new tab**: open a table in the data browser, or another view (text, an image, ...), in a tab of its own.

## Installation

```bash
pip install "jupyter-storage-explorer-launcher[polars]"
```

The launcher has the same extras as `jupyter-storage-explorer`
([Installation](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#installation)), of two kinds:

- **Full extras**, e.g. `[polars]`: the plugin and the libraries it uses.
- **Support-only extras**, e.g. `[polars-support]`: the plugin alone, using the libraries already installed. Nothing
  else is installed or upgraded.

| Full extra | Support-only extra | Plugin                                                              |
|------------|--------------------|---------------------------------------------------------------------|
| `polars`   | `polars-support`   | Polars: Delta Lake, Parquet, CSV, JSON Lines, Excel                 |
| `pandas`   | `pandas-support`   | pandas: Parquet, CSV, JSON Lines, Excel                             |
| `pyspark`  | `pyspark-support`  | PySpark or Databricks Connect: Delta Lake, Parquet, CSV, JSON Lines |
| `abfs`     | `abfs-support`     | Azure Data Lake Storage Gen2                                        |
| `all`      | `all-supports`     | All of the above                                                    |

Full extras are handy for a quick try. **Support-only extras are highly recommended for an IPython kernel whose data
access packages are carefully installed and configured** (e.g. a shared JupyterHub image): the plugins use what is
there and never change it.

```bash
pip install "jupyter-storage-explorer-launcher[all-supports]"  # every plugin, with the libraries you have
```

Install it in the environment of JupyterLab and of the default kernel (on JupyterHub, usually the single-user image),
then restart JupyterLab. Requires JupyterLab 4.0 or later.

Or from JupyterLab itself, without a terminal: run this in a notebook, then reload the page (no restart needed):

```python
%pip install "jupyter-storage-explorer-launcher[polars]"
```

This works when the notebook's kernel runs in JupyterLab's own environment, as the default kernel usually does.

Then see [Using the explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#using-the-explorer).

## Configuration

Click the ⚙ button at the right of the tab's toolbar, then **Edit configuration**.

<img src="https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/settings-button.png" width="164" alt="The settings menu (a gear) after Unsafe mode in the tab's toolbar: Edit configuration and About">

It opens your settings, a Python file (`launcher.py`), in JupyterLab's editor; if you have none, it offers to create
one from a template with an example of each setting.

<img src="https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/settings-editor.png" width="834" alt="launcher.py, created from the template, open in JupyterLab's editor beside the Storage Explorer tab">

Uncomment and edit the settings you need, then save. Reload the web browser, then open the explorer tab again to apply
the changes.

For example, to open each tab on the data lake and the folder it starts on, with a preview at once:

```python
def filesystems():
    return {
        "Here": ".",  # the folder the tab opens on
        "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
    }


def parameters():
    return {"preview_panel": "open"}
```

The file has some of these functions, all optional:

| Function            | Returns                                                                                                                                                                                                                   |
|---------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `filesystems()`     | `{name: URL or fsspec filesystem}`                                                                                                                                                                                        |
| `plugin_options()`  | The plugins' options, by key, e.g. `{"pandas-support": {"enabled": False}}` ([Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#plugins))                                 |
| `format_options()`  | The libraries' options, by library and format ([Format options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#format-options))                                                 |
| `transfer_policy()` | Rules of a [transfer policy](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy)                                                                                    |
| `parameters()`      | Other `StorageExplorer` arguments ([StorageExplorer options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#storageexplorer-options)), e.g. `{"engine_preference": ["pandas"]}` |

The side panel uses the same settings, except its own layout: `height`, `tree_view`, `preview_panel` and `layout` are
not taken from `parameters()` there.

If your file has an error, the tab still opens, without your settings. The error shows above the explorer and in its
status bar. Fix the file with the ⚙ button, then open the tab again. This covers errors raised by the file, settings
that do not exist, and values the explorer refuses.

For extending the explorer in Python
([Developing plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/development-plugin.md)),
tried before the defaults: `supports()` (`FormatSupport`: formats and the libraries handling them), `operations()`
(`FileSystemOperations`) and `filesystem_mappers()` (`FileSystemMapper`).

### Other configuration files

Your files are in Jupyter's configuration directory, which `jupyter --config-dir` prints: `~/.jupyter` by default (on
Windows, `%USERPROFILE%\.jupyter`), or `$JUPYTER_CONFIG_DIR` where that is set. `launcher.py` is in its
`storage-explorer` folder.

#### Icons

To change the explorer's icons, use JupyterLab's `custom.css` (see
[Icons](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md#icons)), which applies to the
launcher's tabs and to explorers in notebooks alike.

#### Bookmarks and query settings

The tabs share bookmarks and the data browser's query settings in `storage-explorer/states.json` in the same
directory, unless `parameters()` sets `states` (another file's path, or `None`: in each tab's memory).

### Layers of the configuration file

Administrators can set up the tab for everyone: a `storage-explorer/launcher.py` in any of Jupyter's configuration
directories (`jupyter --paths`, *config* section) is read, e.g. `/etc/jupyter/storage-explorer/launcher.py` for the
whole system or `<environment>/etc/jupyter/storage-explorer/launcher.py` for one Python environment (e.g. a
JupyterHub image). Each file is a layer, applied from the system's to the user's, so users' files usually come last.
A later layer changes an earlier one's settings this way:

| Function                                             | Merged with earlier layers                      |
|------------------------------------------------------|-------------------------------------------------|
| `filesystems()`                                      | By name: added or replaced; `None` removes one  |
| `plugin_options()`                                   | By plugin, then option                          |
| `parameters()`                                       | By name                                         |
| `format_options()`                                   | By library, format, then option                 |
| `supports()`, `operations()`, `filesystem_mappers()` | Later layers' first, all before the defaults    |
| `transfer_policy()`                                  | Later layers' rules first, so they decide first |

`final()` returns the settings later layers cannot change: function names (except `parameters`) and parameter names.
For example, `/etc/jupyter/storage-explorer/launcher.py`:

```python
def filesystems():
    return {
        "Here": ".",
        "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
    }


def transfer_policy():
    # No downloads from the lake to users' computers or to the Jupyter server.
    return [
        {"rule": "deny", "src": r"abfs://lake@.*", "dest": "browser:///.*"},
        {"rule": "deny", "src": r"abfs://lake@.*", "dest": "jupyterlab://.*"},
    ]


def final():
    return ["filesystems", "transfer_policy"]  # users cannot change these
```

Final settings are not a security boundary: users can still create explorers in notebooks.

An error in any file other than the user's stops the tab: it shows only the error, naming the file. Users' files are
left out instead (see [Configuration](#configuration)).
