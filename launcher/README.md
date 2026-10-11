# Jupyter Storage Explorer launcher

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-storage-explorer-launcher?color=blue)](https://pypi.org/project/jupyter-storage-explorer-launcher/)

Adds **Storage Explorer** to JupyterLab's launcher (section *Other*) and command palette. It opens
[Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/README.md) in its own tab, with a kernel of its own that stops when the tab is closed.

![The Storage Explorer item in JupyterLab's launcher](https://raw.githubusercontent.com/sugibuchi/jupyter-storage-explorer/main/launcher/figs/launcher.png)

The tab opens on the launcher's folder: the one JupyterLab's file browser showed when the launcher was opened (like the
launcher's Notebook and Console items; open a new launcher after changing folder). From the command palette, it opens
on the folder the file browser shows. When the page is reloaded, JupyterLab restores the tab and the explorer is shown
again, from a new run of `launch()` in the same kernel.

```bash
pip install jupyter-storage-explorer-launcher
```

Install it in the environment of JupyterLab and of the default kernel (on JupyterHub, usually the single-user image),
then restart JupyterLab. It installs `jupyter-storage-explorer` too.

What the tab shows is set by a file `storage-explorer/launcher.py` in a Jupyter configuration directory: its `launch()`
function returns the widget. For example, for one user, `~/.jupyter/storage-explorer/launcher.py`:

```python
from jupyter_storage_explorer import StorageExplorer


def launch():
    return StorageExplorer(
        # "." is the folder the tab opens on (see above)
        filesystems={
            "Here": ".",
            "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
        },
        height="fill",  # as tall as the tab
    )
```

Administrators can put one in `/etc/jupyter/storage-explorer/launcher.py` (or `<environment>/etc/jupyter/...`) for
everyone. The directories are searched in Jupyter's usual order (`jupyter --paths`, *config* section) and the first file
found is used. Without one, the tab shows an explorer of the folder it opens on.

The file may also have a `style()` function returning CSS (without `<style>`), e.g. to customize the explorer's icons
(see [Customizing icons](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/DEVELOPMENT.md#customizing-icons)). It applies to the whole JupyterLab page while the tab is
open:

```python
def style():
    # The folders in the top folder as 🗃️ instead of 📁: hide the icon, show another
    return """
    .jse-browser [data-depth="1"] .jse-icon { font-size: 0; }
    .jse-browser [data-depth="1"] .jse-icon::before { font-size: 14px; content: "🗃️"; }
    """
```

It also lets you drag files from any Storage Explorer, in its tab or in a notebook, onto JupyterLab's file browser: after
asking, the explorer's kernel downloads them into the folder dropped on, or the one the file browser shows. This needs
the kernel to run where the Jupyter server does, as it does by default.

Requires JupyterLab 4.
