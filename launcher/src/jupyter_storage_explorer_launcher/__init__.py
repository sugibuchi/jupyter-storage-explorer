"""Jupyter Storage Explorer in the JupyterLab launcher.

The JupyterLab extension (built from labextension/ into this package) adds
the launcher item; the tab it opens runs ``launch()`` (see launcher.py).
"""

from jupyter_storage_explorer_launcher.launcher import launch

__all__ = ["launch"]


def _jupyter_labextension_paths() -> list[dict[str, str]]:
    """The JupyterLab extension, for ``jupyter labextension develop``."""
    return [{"src": "labextension", "dest": "jupyter-storage-explorer-launcher"}]
