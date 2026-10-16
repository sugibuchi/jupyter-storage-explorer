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

```bash
pip install jupyter-storage-explorer-launcher
```

Install it in the environment of JupyterLab and of the default kernel (on JupyterHub, usually the single-user image),
then restart JupyterLab. Requires JupyterLab 4.

## Configuration

Configure the tab with files `storage-explorer/launcher.py` in Jupyter's configuration directories (`jupyter --paths`,
*config* section), e.g. `/etc/jupyter/storage-explorer/launcher.py` for everyone and
`~/.jupyter/storage-explorer/launcher.py` for you. Each file is a layer, applied from the system's to the user's, and
has some of these functions:

| Function            | Returns                                                       | Merged with earlier layers                               |
|---------------------|---------------------------------------------------------------|----------------------------------------------------------|
| `filesystems()`     | `{name: URL or fsspec filesystem}`                            | By name: added or replaced; `None` removes one           |
| `formats()`         | Formats of your own (`DataFormat`), tried before the defaults | Later layers' first                                      |
| `format_options()`  | Options for the default formats ([Format options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#format-options)) | By option name                                           |
| `operations()`      | File operations of your own (`FileSystemOperations`)          | Later layers' first, all before the defaults             |
| `transfer_policy()` | Rules of a [transfer policy](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#transfer-policy) | Later layers' first, so they decide first                |
| `parameters()`      | Other `StorageExplorer` arguments, e.g. `{"height": "fill"}`  | By name                                                  |
| `style()`           | CSS for the page while the tab is open                        | Joined, the user's last                                  |
| `final()`           | Settings later layers cannot change, e.g. `["filesystems"]`   | Function names (except `parameters`) and parameter names |

`"."` is the folder the tab opens on. The tabs share bookmarks and query settings in
`~/.jupyter/storage-explorer/states.json`, unless `parameters()` sets `states` (`None`: in each tab's memory). Final
settings are not a security boundary: users can still create explorers in notebooks.

For example, for everyone, `/etc/jupyter/storage-explorer/launcher.py`:

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

And for one user, `~/.jupyter/storage-explorer/launcher.py`, with icons of their own (see
[Customizing icons](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md#customizing-icons)):

```python
def parameters():
    return {"max_browser_items": 50_000}


def style():
    # The folders in the top folder as 🗃️: hide the folder icon, show another
    return """
    .jse-browser [data-depth="1"] .jse-icon svg { display: none; }
    .jse-browser [data-depth="1"] .jse-icon::before { content: "🗃️"; }
    """
```
