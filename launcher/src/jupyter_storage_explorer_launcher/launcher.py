"""Opening Storage Explorer from the JupyterLab launcher.

The "Storage Explorer" item in the launcher opens a new tab with a fresh
kernel, started in the launcher's folder (the one JupyterLab's file browser
showed), which runs ``launch()``; it runs again in the same kernel when the
page is reloaded. It looks for a file
``storage-explorer/launcher.py`` in Jupyter's configuration directories,
in the order Jupyter searches them (``jupyter --paths``: e.g. ``~/.jupyter``,
``<env>/etc/jupyter``, ``/usr/local/etc/jupyter``, ``/etc/jupyter``); the
first one found is used. Its ``launch()`` function returns the widget to show,
for example::

    # ~/.jupyter/storage-explorer/launcher.py
    from jupyter_storage_explorer import StorageExplorer

    def launch():
        return StorageExplorer(
            # "." is the folder the kernel started in
            filesystems={
                "Here": ".",
                "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
            },
            height="fill",  # as tall as the tab
        )

Without such a file, the tab shows a ``StorageExplorer`` of the folder
the kernel started in.

The file may also have a ``style()`` function returning CSS (without
``<style>``), e.g. to customize the explorer's icons; it applies to the page
while the tab is open::

    def style():
        return '.jse-browser [data-depth="1"] .jse-icon { filter: hue-rotate(180deg); }'
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

from jupyter_core.paths import jupyter_config_path

# Looked for in each Jupyter configuration directory.
LAUNCHER_FILE = pathlib.Path("storage-explorer", "launcher.py")


def find_launcher_file() -> pathlib.Path | None:
    """The launcher.py to use: the first in Jupyter's configuration directories."""
    for directory in jupyter_config_path():
        path = pathlib.Path(directory) / LAUNCHER_FILE
        if path.is_file():
            return path
    return None


def _load(path: pathlib.Path) -> Any:
    """Import ``path`` as a module of its own."""
    spec = importlib.util.spec_from_file_location("storage_explorer_launcher", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launcher() -> tuple[pathlib.Path | None, Any]:
    """The launcher.py found and its module, or (None, None)."""
    path = find_launcher_file()
    return (path, _load(path)) if path is not None else (None, None)


def _create_widget(path: pathlib.Path | None, module: Any) -> Any:
    """The widget from the launcher.py's ``launch()``; without a launcher.py, a
    default explorer."""
    if module is None:
        from jupyter_storage_explorer import StorageExplorer  # noqa: PLC0415

        return StorageExplorer(".", height="fill")
    function = getattr(module, "launch", None)
    if not callable(function):
        raise AttributeError(f"{path} has no launch() function")
    return function()


def _style(module: Any) -> str:
    """CSS from the launcher.py's optional ``style()``; "" without one."""
    function = getattr(module, "style", None)
    return (function() or "") if callable(function) else ""


def create_widget() -> Any:
    """The widget to show: from the launcher.py found, else a default explorer."""
    return _create_widget(*_launcher())


def launch() -> None:
    """Run by the launcher's tab: apply the launcher.py's ``style()``, if any,
    and show the widget its ``launch()`` returns."""
    from IPython.display import HTML, display  # noqa: PLC0415

    path, module = _launcher()
    css = _style(module)
    if css:
        # A <style> output applies to the whole page while the tab is open;
        # the tab's CSS hides the (empty) output itself.
        display(HTML(f"<style>{css}</style>"))
    widget = _create_widget(path, module)
    if widget is not None:  # launch() may also display things itself
        display(widget)
