"""StorageExplorer's "About" (a mixin of the class): the explorer's name,
version and icon, and the plugins installed."""

from __future__ import annotations

import base64
from importlib.metadata import PackageNotFoundError, distribution, version
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._plugins import installed_plugins
from jupyter_storage_explorer._static import STATIC
from jupyter_storage_explorer.plugin import (
    homepage,
    package_authors,
    package_license,
    package_urls,
)

if TYPE_CHECKING:
    from importlib.metadata import Distribution

    from jupyter_storage_explorer.plugin import StorageExplorerPlugin

# The explorer's own icon, the launcher's (launcher/labextension/style/):
# tests/explorer/test_explorer_about.py keeps the two copies the same.
_ICON = "storage-explorer.svg"


def _explorer_version() -> str:
    try:
        return version("jupyter-storage-explorer")
    except PackageNotFoundError:  # run from a source tree not installed
        return ""


def _explorer_distribution() -> Distribution | None:
    try:
        return distribution("jupyter-storage-explorer")
    except PackageNotFoundError:
        return None


def _package_details(dist: Distribution | None) -> dict[str, Any]:
    """{"authors", "license", "homepage"} of a package, from its metadata
    (see plugin.py's ``package_*``); empty ones without it."""
    if dist is None:
        return {"authors": [], "license": "", "homepage": ""}
    return {
        "authors": package_authors(dist),
        "license": package_license(dist) or "",
        "homepage": homepage(package_urls(dist)) or "",
    }


def _icon_url() -> str:
    """The icon as a data URL, for an <img> (scripts in it never run)."""
    data = (STATIC / _ICON).read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


class AboutMixin:
    """The "About" dialog's contents ("about")."""

    _plugins: list[StorageExplorerPlugin]
    _plugin_problems: list[str]

    def _about(self) -> dict[str, Any]:
        """{"name", "version", "icon", "authors", "license", "homepage",
        "plugins"}: the explorer's, and the plugins installed, by package
        name, each {"key", "name", "version", "description", "authors",
        "license", "homepage", "enabled", "note"}; "note" says why one is not
        used (disabled, or could not be loaded). Read from the packages'
        metadata, so plugins not loaded are listed without being imported."""
        loaded = {p.key: p for p in self._plugins}
        plugins = []
        for key, registered in installed_plugins().items():
            plugin = loaded.get(key)
            dist = plugin.distribution if plugin is not None else registered[0].dist
            plugins.append(
                {
                    "key": key,
                    "name": dist.metadata["Name"] if dist is not None else key,
                    "version": dist.version if dist is not None else "",
                    "description": dist.metadata["Summary"] or ""
                    if dist is not None
                    else "",
                    **_package_details(dist),
                    "enabled": plugin is not None,
                    "note": "" if plugin is not None else self._plugin_note(key),
                }
            )
        plugins.sort(key=lambda p: p["name"].lower())
        return {
            "name": "Jupyter Storage Explorer",
            "version": _explorer_version(),
            "icon": _icon_url(),
            **_package_details(_explorer_distribution()),
            "plugins": plugins,
        }

    def _plugin_note(self, key: str) -> str:
        """Why the plugin ``key`` is not used."""
        prefix = f"plugin {key!r} not loaded: "
        problem = next((p for p in self._plugin_problems if p.startswith(prefix)), None)
        if problem is not None:
            return f"Not loaded: {problem.removeprefix(prefix)}"
        return "Disabled"
