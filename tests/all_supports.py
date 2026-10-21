"""The supports an explorer has with every plugin of the repository installed
(as in development): the plugins' (by key), then the core's."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer._plugins import PluginComponents, load_plugins
from jupyter_storage_explorer.formats.defaults import DEFAULT_SUPPORTS

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats import FormatSupport

PLUGINS, _problems = load_plugins(None)
assert not _problems, _problems

ALL_SUPPORTS: tuple[type[FormatSupport], ...] = (
    *PluginComponents(PLUGINS).supports,
    *DEFAULT_SUPPORTS,
)


def all_supports() -> list[FormatSupport]:
    """``ALL_SUPPORTS``, created."""
    return [cls() for cls in ALL_SUPPORTS]
