"""Loading plugins (``StorageExplorerPlugin``) from their entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from jupyter_storage_explorer.plugin import ENTRY_POINT_GROUP, StorageExplorerPlugin

if TYPE_CHECKING:
    from collections.abc import Sequence
    from importlib.metadata import EntryPoint

    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport


def installed_plugins() -> dict[str, list[EntryPoint]]:
    """The plugins' entry points, by name (a list, so that two packages
    registering one name are told apart from one)."""
    found: dict[str, list[EntryPoint]] = {}
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        found.setdefault(entry_point.name, []).append(entry_point)
    return found


def load_plugins(
    keys: Sequence[str] | None,
) -> tuple[list[type[StorageExplorerPlugin]], list[str]]:
    """The plugins ``keys`` names, in its order, or every one installed, by
    key; and why some were not loaded.

    Only the plugins named are imported. ValueError for a key no plugin
    installed has, as a typo would otherwise go unnoticed. A plugin that
    cannot be imported, is no ``StorageExplorerPlugin`` or names another key
    is left out, with its reason: a broken package must not keep the
    explorer from opening.
    """
    found = installed_plugins()
    if keys is None:
        names = sorted(found)
    else:
        unknown = [key for key in keys if key not in found]
        if unknown:
            raise ValueError(
                f"plugins: {unknown} not installed; installed: {sorted(found)}"
            )
        names = list(dict.fromkeys(keys))
    plugins: list[type[StorageExplorerPlugin]] = []
    problems: list[str] = []
    for name in names:
        if len(found[name]) > 1:
            packages = sorted(
                str(e.dist.name if e.dist else e.value) for e in found[name]
            )
            problems.append(f"plugin {name!r} not loaded: registered by {packages}")
            continue
        try:
            plugin = found[name][0].load()
        except Exception as exc:
            problems.append(f"plugin {name!r} not loaded: {type(exc).__name__}: {exc}")
            continue
        if not (isinstance(plugin, type) and issubclass(plugin, StorageExplorerPlugin)):
            problems.append(
                f"plugin {name!r} not loaded: {plugin!r} is no StorageExplorerPlugin"
            )
        elif getattr(plugin, "key", None) != name:
            problems.append(
                f"plugin {name!r} not loaded: its class's key is "
                f"{getattr(plugin, 'key', None)!r}"
            )
        else:
            plugins.append(plugin)
    return plugins, problems


class PluginComponents:
    """What ``plugins`` give, in their order: supports and formats as
    classes, operations and mappers created (without arguments)."""

    def __init__(self, plugins: Sequence[type[StorageExplorerPlugin]]) -> None:
        self.supports: list[type[FormatSupport]] = [
            s for p in plugins for s in p.format_supports
        ]
        self.formats: list[type[DataFormat]] = [f for p in plugins for f in p.formats]
        self.operations: list[FileSystemOperations] = [
            cls() for p in plugins for cls in p.filesystem_operations
        ]
        self.mappers: list[FileSystemMapper] = [
            cls() for p in plugins for cls in p.filesystem_mappers
        ]
