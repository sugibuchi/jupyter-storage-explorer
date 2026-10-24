"""The supports an explorer has with every plugin of the repository installed
(as in development): the plugins' (by key), then the core's."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._plugins import PluginComponents, load_plugins
from jupyter_storage_explorer.formats.defaults import DEFAULT_ACTIONS
from jupyter_storage_explorer.formats.package import PythonPackage

if TYPE_CHECKING:
    import pytest

    from jupyter_storage_explorer.formats import FormatSupport
    from jupyter_storage_explorer.formats.actions import Action

PLUGINS, _problems = load_plugins()
assert not _problems, _problems

# plugin_options disabling every plugin: the core alone.
NO_PLUGINS = {p.key: {"enabled": False} for p in PLUGINS}

# The plugins' supports of the former interface (classes), then the core's
# actions.
ALL_SUPPORTS: tuple[type[FormatSupport] | Action[Any], ...] = (
    *PluginComponents(PLUGINS).actions,
    *DEFAULT_ACTIONS,
)


def all_supports() -> list[FormatSupport | Action[Any]]:
    """``ALL_SUPPORTS``, the classes created."""
    return [s() if isinstance(s, type) else s for s in ALL_SUPPORTS]


def installed_only(monkeypatch: pytest.MonkeyPatch, *packages: str) -> None:
    """Make ``packages`` (pip names) the only ones installed, whatever the
    development environment has: the engines offered depend on them."""
    monkeypatch.setattr(
        PythonPackage, "is_installed", lambda self: self.package in packages
    )
