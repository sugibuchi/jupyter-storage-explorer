"""The actions an explorer has with every plugin of the repository installed
(as in development): the plugins' (by key), then the core's."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._extensions.plugins import PluginComponents, load_plugins
from jupyter_storage_explorer.formats.defaults import DEFAULT_ACTIONS
from jupyter_storage_explorer.formats.packages import PythonPackage

if TYPE_CHECKING:
    import pytest

    from jupyter_storage_explorer.formats.actions import Action

PLUGINS, _problems = load_plugins()
assert not _problems, _problems

# plugin_options disabling every plugin: the core alone.
NO_PLUGINS = {p.key: {"enabled": False} for p in PLUGINS}

# The plugins' actions, then the core's.
ALL_ACTIONS: tuple[Action[Any], ...] = (
    *PluginComponents(PLUGINS).actions,
    *DEFAULT_ACTIONS,
)


def all_actions() -> list[Action[Any]]:
    """``ALL_ACTIONS``, as a list."""
    return list(ALL_ACTIONS)


def installed_only(monkeypatch: pytest.MonkeyPatch, *packages: str) -> None:
    """Make ``packages`` (pip names) the only ones installed, whatever the
    development environment has: the engines offered depend on them."""
    monkeypatch.setattr(
        PythonPackage, "is_installed", lambda self: self.package in packages
    )
