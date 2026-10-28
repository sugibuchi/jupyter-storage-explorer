"""Helpers for testing plugins without a browser: the check of a plugin as
explorers load it (``check_plugin``), and items as the explorer gives them to
formats and actions (``ItemContext``), on fsspec's memory filesystem or local
files.

Needs pytest (for the fixtures). In a plugin's ``tests/conftest.py``::

    from jupyter_storage_explorer.testing import make_item, memfs  # noqa: F401

then, in its tests::

    def test_plugin():
        check_plugin("duckdb-support")


    def test_view(make_item):
        item = make_item("/a.csv", b"x,y\\n1,2\\n")
        view = csv_view(Csv(), item, CsvByDuckDBOptions(), ViewLimits())
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import TYPE_CHECKING, Any

import fsspec
import pytest
from fsspec.implementations.memory import MemoryFileSystem

from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer._extensions.plugins import (
    PluginComponents,
    _create,
    installed_plugins,
    load_plugins,
)
from jupyter_storage_explorer.actions import Action, register_actions
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.filesystems import MapperChain, default_mappers
from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
from jupyter_storage_explorer.formats.base import DataFormat
from jupyter_storage_explorer.formats.defaults import DEFAULT_FORMATS
from jupyter_storage_explorer.plugin import (
    ENTRY_POINT_GROUP,
    StorageExplorerPluginOptions,
)
from jupyter_storage_explorer.storage_explorer import StorageExplorer

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from jupyter_storage_explorer.base import Location
    from jupyter_storage_explorer.plugin import StorageExplorerPlugin

__all__ = ["check_plugin", "item_of", "local_item", "make_item", "memfs"]


def check_plugin(
    key: str, options: Mapping[str, Any] | None = None
) -> StorageExplorerPlugin:
    """The plugin installed as ``key``, loaded as explorers load it, after
    checking what they would only log or fail on.

    Explorers leave out a plugin they cannot load, with a warning, so that a
    broken package never keeps them from opening. This check fails instead,
    for a plugin's tests. It checks:

    - its entry point, in the group ``"jupyter_storage_explorer.plugins"``,
      named by the plugin's ``key``, and the class it names;
    - its ``options_model``, created from ``options``;
    - its package's description, shown in "About";
    - its components: actions registered together, ``DataFormat`` classes,
      ``FileSystemOperations`` and ``FileSystemMapper`` objects or classes;
    - its actions together with the explorer's own and those of the other
      plugins installed, as an explorer checks them when it is created.

    What a component does, e.g. a ``check`` reading nothing, is for the
    plugin's own tests.

    Parameters
    ----------
    key : str
        The plugin's key, e.g. "duckdb-support".
    options : mapping, optional
        Its options, as ``StorageExplorer(plugin_options={key: options})``
        takes them; by default its options model's defaults.

    Returns
    -------
    StorageExplorerPlugin
        The plugin, created with ``options``, for further checks.

    Raises
    ------
    AssertionError
        Naming every problem found.
    ValueError
        For an option its options model has no field of.

    Examples
    --------
    >>> def test_plugin():
    ...     plugin = check_plugin("duckdb-support", {"databases": False})
    ...     assert database_view not in plugin.actions
    """
    registered = installed_plugins().get(key)
    if not registered:
        raise AssertionError(
            f"no plugin {key!r} installed: no entry point of that name in the "
            f"group {ENTRY_POINT_GROUP!r}. After adding it to pyproject.toml, "
            "install the package again, e.g. with uv sync."
        )
    problems: list[str] = []
    plugin = _create(key, registered, dict(options or {}), problems)
    if plugin is None:
        raise AssertionError(problems[0])
    problems.extend(_options_model_problems(type(plugin).options_model))
    if not plugin.description:
        problems.append(
            "its package has no description: pyproject.toml's [project] "
            "description, which About shows"
        )
    problems.extend(_component_problems(plugin))
    if not problems:
        # As an explorer has them: with the other plugins enabled.
        others, _ = load_plugins()
        plugins = [p for p in others if p.key != key] + [plugin]
        problems.extend(_chain_problems(plugins))
    if problems:
        raise AssertionError(
            f"plugin {key!r}:\n" + "\n".join(f"- {p}" for p in problems)
        )
    return plugin


def _options_model_problems(model: Any) -> list[str]:
    """What keeps ``model`` from being a plugin's options model: a frozen,
    keyword-only dataclass subclassing ``StorageExplorerPluginOptions``."""
    if not (
        isinstance(model, type) and issubclass(model, StorageExplorerPluginOptions)
    ):
        return [f"options_model {model!r} is no StorageExplorerPluginOptions subclass"]
    # Its own: a subclass not decorated inherits its base's.
    params = model.__dict__.get("__dataclass_params__")
    if (
        params is None
        or not params.frozen
        or not all(f.kw_only for f in dataclasses.fields(model))
    ):
        return [
            f"options_model {model.__qualname__} must be "
            "@dataclass(frozen=True, kw_only=True)"
        ]
    return []


def _component_problems(plugin: StorageExplorerPlugin) -> list[str]:
    """What is wrong with ``plugin``'s components, each on its own."""
    problems: list[str] = []
    actions = list(plugin.actions)
    if any(not isinstance(a, Action) for a in actions):
        problems.extend(
            f"actions: {a!r} is no action; decorate it with @view or @code"
            for a in actions
            if not isinstance(a, Action)
        )
    else:
        try:
            register_actions(*actions)
        except (TypeError, ValueError) as exc:
            problems.append(f"actions: {exc}")
    problems.extend(
        f"formats: {f!r} is no DataFormat class"
        for f in plugin.formats
        if not (isinstance(f, type) and issubclass(f, DataFormat))
    )
    for name, kind, components in [
        (
            "filesystem_operations",
            FileSystemOperations,
            plugin.filesystem_operations,
        ),
        ("filesystem_mappers", FileSystemMapper, plugin.filesystem_mappers),
    ]:
        for component in components:
            if isinstance(component, type) and issubclass(component, kind):
                try:
                    component()  # as explorers create it
                except Exception as exc:
                    problems.append(
                        f"{name}: {component.__qualname__}() fails: "
                        f"{type(exc).__name__}: {exc}"
                    )
            elif not isinstance(component, kind):
                problems.append(f"{name}: {component!r} is no {kind.__name__}")
    return problems


def _chain_problems(plugins: list[StorageExplorerPlugin]) -> list[str]:
    """What keeps ``plugins``' actions and formats from an explorer, with its
    own: what ``ActionChain`` refuses."""
    components = PluginComponents(plugins)
    try:
        ActionChain(
            [*components.actions, *StorageExplorer.default_actions()],
            formats=[*components.formats, *DEFAULT_FORMATS],
        )
    except (TypeError, ValueError) as exc:
        others = ", ".join(p.key for p in plugins[:-1]) or "none"
        return [
            f"with the explorer's own actions and the other plugins' ({others}): {exc}"
        ]
    return []


def item_of(fs: Any, path: str, location: Location | None = None) -> ItemContext:
    """The item at ``path`` of ``fs``, as explorers detect and read it.

    Parameters
    ----------
    fs : fsspec.AbstractFileSystem
        The filesystem the item is on.
    path : str
        Its path there.
    location : Location, optional
        Where it is; by default from the default mappers (e.g. an
        ``S3Location`` to test code reading from S3).

    Returns
    -------
    ItemContext
        With its fsspec info, and its listing for a folder.
    """
    info: dict[str, Any] = fs.info(path)
    children = fs.ls(path, detail=True) if info["type"] == "directory" else None
    if location is None:
        location = MapperChain(default_mappers()).location_of(fs, path)
    return ItemContext(
        location=location, fs=fs, path=path, info=info, children=children
    )


def local_item(path: str | pathlib.Path) -> ItemContext:
    """A local file or folder, for libraries reading by URL (e.g. polars,
    which cannot read fsspec's memory filesystem).

    Parameters
    ----------
    path : str or pathlib.Path
        The local path, e.g. in pytest's ``tmp_path``.

    Returns
    -------
    ItemContext
    """
    return item_of(fsspec.filesystem("file"), pathlib.Path(path).as_posix())


@pytest.fixture
def memfs() -> MemoryFileSystem:
    """An empty in-memory filesystem: fsspec keeps one store per process, so
    it is cleared."""
    fs = fsspec.filesystem("memory")
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs.clear()
    MemoryFileSystem.pseudo_dirs.append("")
    return fs


@pytest.fixture
def make_item(memfs: MemoryFileSystem) -> Callable[..., ItemContext]:
    """A function writing a file (``data``) or listing a folder on ``memfs``
    and returning it as an ``ItemContext``: ``make_item(path, data=None,
    location=None)``, ``location`` instead of its own, e.g. an S3 one."""

    def make(
        path: str, data: bytes | None = None, location: Location | None = None
    ) -> ItemContext:
        if data is not None:
            memfs.pipe_file(path, data)
        return item_of(memfs, path, location)

    return make
