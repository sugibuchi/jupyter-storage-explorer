# Jupyter Storage Explorer launcher

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer-launcher?color=blue)](https://pypi.org/project/jupyter-storage-explorer-launcher/)

Adds **Storage Explorer** to JupyterLab's launcher (section *Other*) and command palette. It opens
[Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/README.md) in its own tab, on
the folder JupyterLab's file browser shows.

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

It also integrates every Storage Explorer, in its tab or in a notebook, with JupyterLab:

- **Drag and drop**: drag files onto JupyterLab's file browser to download them there.
- **Open files in a tab**: double-click a file to open it in JupyterLab's own editor or viewer; **Save** writes it back
  to the storage.
- **Query data in a tab**: open the data browser in a tab of its own.

## Installation

```bash
pip install jupyter-storage-explorer-launcher
```

Install it in the environment of JupyterLab and of the default kernel (on JupyterHub, usually the single-user image),
then restart JupyterLab. Requires JupyterLab 4.0 or later.

Or from JupyterLab itself, without a terminal: run this in a notebook, then reload the page (no restart needed):

```python
%pip install jupyter-storage-explorer-launcher
```

This works when the notebook's kernel runs in JupyterLab's own environment, as the default kernel usually does.

Then see [Using the explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#using-the-explorer).

## Configuration

Click the ⚙ button at the right of the tab's toolbar.

<img src="https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/settings-button.png" width="152" alt="The settings button (a gear) after Unsafe mode in the tab's toolbar">

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
    return {"open_preview": True}
```

The file has some of these functions, all optional:

| Function               | Returns                                                                                   |
|------------------------|-------------------------------------------------------------------------------------------|
| `filesystems()`        | `{name: URL or fsspec filesystem}`                                                        |
| `formats()`            | Formats of your own (`DataFormat`), tried before the defaults                             |
| `supports()`           | [Libraries of your own for formats](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#another-library-for-a-format) (`FormatSupport`), tried before the defaults |
| `format_options()`     | The libraries' options, by library and format ([Format options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#format-options)) |
| `operations()`         | File operations of your own (`FileSystemOperations`), tried before the defaults           |
| `filesystem_mappers()` | The locations of storages' paths (`FileSystemMapper`), by which [storages are told apart](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#file-transfer-between-file-systems) |
| `transfer_policy()`    | Rules of a [transfer policy](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy) |
| `parameters()`         | Other `StorageExplorer` arguments ([StorageExplorer options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#storageexplorer-options)), e.g. `{"height": "fill"}` |

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

| Function                                        | Merged with earlier layers                     |
|-------------------------------------------------|------------------------------------------------|
| `filesystems()`                                 | By name: added or replaced; `None` removes one |
| `parameters()`                                  | By name                                        |
| `format_options()`                              | By library, format, then option                |
| `formats()`, `supports()`, `operations()`, `filesystem_mappers()` | Later layers' first, all before the defaults |
| `transfer_policy()`                             | Later layers' rules first, so they decide first |

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
