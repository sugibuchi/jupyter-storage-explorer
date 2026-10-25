"""Loading plugins (``StorageExplorerPlugin``) from their entry points, with
their options."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.plugin import ENTRY_POINT_GROUP, StorageExplorerPlugin

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from importlib.metadata import EntryPoint

    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats.actions import Action
    from jupyter_storage_explorer.formats.base import DataFormat


def installed_plugins() -> dict[str, list[EntryPoint]]:
    """The plugins' entry points, by name (a list, so that two packages
    registering one name are told apart from one)."""
    found: dict[str, list[EntryPoint]] = {}
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        found.setdefault(entry_point.name, []).append(entry_point)
    return found


def load_plugins(
    plugin_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[StorageExplorerPlugin], list[str]]:
    """The plugins installed and enabled, created with their options
    (``plugin_options`` by key), highest priority first, then by key; and
    why some were not loaded.

    A plugin whose options say ``"enabled": False`` is not imported. One
    that cannot be imported or created, is no ``StorageExplorerPlugin``,
    names another key or is registered twice is left out, with its reason:
    a broken package must not keep the explorer from opening. So are options
    of plugins not installed (shared settings may name plugins an
    environment lacks). ValueError for options no field of a plugin's
    ``options_model`` takes, as a typo would otherwise go unnoticed.
    """
    plugin_options = plugin_options or {}
    found = installed_plugins()
    problems = [
        f"plugin_options: plugin {key!r} is not installed"
        for key in plugin_options
        if key not in found
    ]
    plugins: list[StorageExplorerPlugin] = []
    for name in sorted(found):
        values = dict(plugin_options.get(name) or {})
        if values.get("enabled", True) is False:
            continue
        plugin = _create(name, found[name], values, problems)
        if plugin is not None and plugin.options.enabled:
            plugins.append(plugin)
    # Stable: those of one priority stay in the order of their keys.
    plugins.sort(key=lambda p: -p.options.priority)
    return plugins, problems


def _create(
    name: str,
    registered: list[EntryPoint],
    values: dict[str, Any],
    problems: list[str],
) -> StorageExplorerPlugin | None:
    """The plugin registered as ``name``, created with the options
    ``values``; None, and its reason in ``problems``, if it cannot be."""
    if len(registered) > 1:
        packages = sorted(str(e.dist.name if e.dist else e.value) for e in registered)
        problems.append(f"plugin {name!r} not loaded: registered by {packages}")
        return None
    try:
        cls = registered[0].load()
    except Exception as exc:
        problems.append(f"plugin {name!r} not loaded: {type(exc).__name__}: {exc}")
        return None
    if not (isinstance(cls, type) and issubclass(cls, StorageExplorerPlugin)):
        problems.append(
            f"plugin {name!r} not loaded: {cls!r} is no StorageExplorerPlugin"
        )
        return None
    if getattr(cls, "key", None) != name:
        problems.append(
            f"plugin {name!r} not loaded: its class's key is {getattr(cls, 'key', None)!r}"
        )
        return None
    model = cls.options_model
    unknown = values.keys() - model.option_names()
    if unknown:
        raise ValueError(
            f"plugin_options[{name!r}]: unknown options {sorted(unknown)}; "
            f"choose from {sorted(model.option_names())}"
        )
    try:
        plugin = cls(model(**values))
    except Exception as exc:
        problems.append(f"plugin {name!r} not loaded: {type(exc).__name__}: {exc}")
        return None
    # Its package's metadata (name, description, version): the entry point's.
    plugin._distribution = registered[0].dist
    return plugin


class PluginComponents:
    """What ``plugins`` give, in their order: actions, formats (classes),
    operations and mappers (objects; classes are created without
    arguments)."""

    def __init__(self, plugins: Sequence[StorageExplorerPlugin]) -> None:
        self.actions: list[Action[Any]] = [a for p in plugins for a in p.actions]
        self.formats: list[type[DataFormat]] = [f for p in plugins for f in p.formats]
        self.operations: list[FileSystemOperations] = [
            _created(o) for p in plugins for o in p.filesystem_operations
        ]
        self.mappers: list[FileSystemMapper] = [
            _created(m) for p in plugins for m in p.filesystem_mappers
        ]


def _created(component: Any) -> Any:
    """``component``, created (without arguments) if it is a class."""
    return component() if isinstance(component, type) else component
