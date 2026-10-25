"""Plugins: what a package adds to every explorer (``StorageExplorerPlugin``),
found through its entry point in the group ``ENTRY_POINT_GROUP``, and their
options (``StorageExplorerPluginOptions``)."""

from __future__ import annotations

import dataclasses
import functools
from dataclasses import dataclass
from email.utils import getaddresses
from importlib.metadata import distribution, entry_points, packages_distributions
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Sequence
    from importlib.metadata import Distribution

    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats.actions import Action
    from jupyter_storage_explorer.formats.base import DataFormat

# The entry point group plugins register their class in, named by its key.
ENTRY_POINT_GROUP = "jupyter_storage_explorer.plugins"

# The default priority: the lowest (Java's Integer.MIN_VALUE), so that a
# plugin given any priority comes before those given none.
LOWEST_PRIORITY = -(2**31)


@dataclass(frozen=True, kw_only=True)
class StorageExplorerPluginOptions:
    """The options of a plugin, from ``StorageExplorer(plugin_options=...)``
    (by plugin key, a dict of options): those of every plugin, and the
    fields of a subclass, a plugin's ``options_model``, each with a default.

    Attributes
    ----------
    enabled : bool, default True
        Whether the explorer uses the plugin; a plugin not enabled is not
        even imported.
    priority : int, default the lowest
        Plugins of a higher priority come first: their actions, operations
        and mappers are tried before the others'. Plugins of one priority
        come by key.
    """

    enabled: bool = True
    priority: int = LOWEST_PRIORITY

    @classmethod
    def option_names(cls) -> frozenset[str]:
        """The options the model has: its fields."""
        return frozenset(f.name for f in dataclasses.fields(cls))


class StorageExplorerPlugin:
    """What a package adds to the explorer: support for an engine (e.g.
    DuckDB) or a filesystem (e.g. Azure Data Lake Storage).

    A plugin is a subclass, registered as an entry point of the group
    ``"jupyter_storage_explorer.plugins"``, named by its ``key``. Each
    explorer creates the plugins installed with their options (its
    ``plugin_options``, as an ``options_model`` object, ``self.options``),
    and uses what their properties give after what the explorer is given and
    before its own defaults.

    Conventions: one plugin per engine or filesystem, in a package named
    ``jupyter-storage-explorer-<name>-support``, described (its
    ``pyproject.toml``'s ``description``, shown to users) as "<Name> support
    for Storage Explorer". The libraries it uses are not dependencies of the
    package (shared Jupyter environments install and configure them with
    care, and a plugin must not change them): its ``full`` extra installs
    them. Import them only inside functions, as actions do.

    Parameters
    ----------
    options : StorageExplorerPluginOptions, optional
        Its options, an ``options_model`` object; by default the model's
        defaults.

    Attributes
    ----------
    key : str
        Identifier, the entry point's name, e.g. "duckdb-support": what
        ``plugin_options`` are given by.
    options_model : type, default StorageExplorerPluginOptions
        The class of its options: a frozen, keyword-only dataclass
        subclassing ``StorageExplorerPluginOptions``, each field with a
        default.
    options : StorageExplorerPluginOptions
        Its options, for the properties to choose its components with, e.g.
        which actions to give.
    name, description, version : str or None
        Its package's name, description (shown to users, e.g. "DuckDB
        support for Storage Explorer") and version, as its
        ``pyproject.toml`` gives them (``[project]``'s ``name``,
        ``description`` and the version uv builds): read from the package's
        metadata, installed with it (also by ``uv sync``, editable), not set
        in the class. None for a plugin of no installed package, e.g. a class
        defined in a notebook.
    authors, license, urls : list of str, str or None, dict of str to str
        Its package's authors and maintainers by name, license (e.g. "MIT")
        and links by label (http and https only), from ``[project]``'s
        ``authors``, ``maintainers``, ``license`` and ``[project.urls]``,
        read as ``name`` is; shown in the explorer's About, with the name
        linking to the home page. Empty or None without them.
    actions : sequence of Action
        What the plugin does with formats' data, in the order tried:
        functions decorated with ``formats.actions.view`` or ``code``, given
        as ``register_actions(...)``; their formats are detected too.
    formats : sequence of DataFormat classes
        Formats of the plugin's own that none of its actions names (rare:
        an action names its format).
    filesystem_operations : sequence of FileSystemOperations
        File operations, tried before the default ones.
    filesystem_mappers : sequence of FileSystemMapper
        How the plugin's filesystems are told apart, tried before the
        default mappers.

    Examples
    --------
    In the package, the plugin and its options:

    >>> @dataclass(frozen=True, kw_only=True)
    ... class DuckDBSupportOptions(StorageExplorerPluginOptions):
    ...     databases: bool = True
    >>> class DuckDBSupport(StorageExplorerPlugin):
    ...     key = "duckdb-support"
    ...     options_model = DuckDBSupportOptions
    ...
    ...     @property
    ...     def actions(self):
    ...         databases = (database_view,) if self.options.databases else ()
    ...         return register_actions(parquet_view, parquet_as_relation, *databases)

    its entry point, in ``pyproject.toml``:

    .. code-block:: toml

        [project.entry-points."jupyter_storage_explorer.plugins"]
        duckdb-support = "jupyter_storage_explorer_duckdb_support:DuckDBSupport"

    and an explorer giving it options, and disabling another plugin:

    >>> StorageExplorer(plugin_options={
    ...     "duckdb-support": {"databases": False, "priority": 10},
    ...     "pandas-support": {"enabled": False},
    ... })
    """

    key: ClassVar[str]
    options_model: ClassVar[type[StorageExplorerPluginOptions]] = (
        StorageExplorerPluginOptions
    )

    # The installed package the plugin comes from: its entry point's (set by
    # the explorer), else found by the class's top-level package.
    _distribution: Distribution | None = None

    def __init__(self, options: StorageExplorerPluginOptions | None = None) -> None:
        self.options = options if options is not None else self.options_model()

    @property
    def distribution(self) -> Distribution | None:
        """The installed package the plugin comes from, or None."""
        if self._distribution is None:
            self._distribution = _distribution_of(type(self))
        return self._distribution

    @property
    def name(self) -> str | None:
        dist = self.distribution
        return dist.metadata["Name"] if dist is not None else None

    @property
    def description(self) -> str | None:
        dist = self.distribution
        return dist.metadata["Summary"] if dist is not None else None

    @property
    def version(self) -> str | None:
        dist = self.distribution
        return dist.version if dist is not None else None

    @property
    def authors(self) -> list[str]:
        """The package's authors and maintainers, by name (``[project]``'s
        ``authors`` and ``maintainers``, without their emails); empty if it
        names none, or there is no package."""
        dist = self.distribution
        return package_authors(dist) if dist is not None else []

    @property
    def license(self) -> str | None:
        """The package's license, as ``[project]``'s ``license`` gives it
        (an SPDX expression, e.g. "MIT"), or None."""
        dist = self.distribution
        return package_license(dist) if dist is not None else None

    @property
    def urls(self) -> dict[str, str]:
        """The package's links by label, e.g. {"Homepage": "https://..."}
        (``[project.urls]``): http and https ones only."""
        dist = self.distribution
        return package_urls(dist) if dist is not None else {}

    @property
    def actions(self) -> Sequence[Action[Any]]:
        return ()

    @property
    def formats(self) -> Sequence[type[DataFormat]]:
        return ()

    @property
    def filesystem_operations(self) -> Sequence[FileSystemOperations]:
        return ()

    @property
    def filesystem_mappers(self) -> Sequence[FileSystemMapper]:
        return ()


# What the package's metadata calls its home page, in order of preference.
_HOMEPAGE_LABELS = ("homepage", "home", "repository", "source", "documentation")


def package_authors(dist: Distribution) -> list[str]:
    """The names in a package's ``Author``, ``Author-email``, ``Maintainer``
    and ``Maintainer-email`` metadata, each once, emails left out (an author
    given by email only is too)."""
    names: list[str] = []
    metadata = dist.metadata
    for field in ("Author", "Maintainer"):
        names.extend(n.strip() for n in (metadata.get(field) or "").split(","))
        emails = metadata.get(f"{field}-email") or ""
        names.extend(name for name, _ in getaddresses([emails]))
    return list(dict.fromkeys(n for n in names if n))


def package_license(dist: Distribution) -> str | None:
    """A package's ``License-Expression`` (e.g. "MIT"); else its legacy
    ``License``, when it is a name rather than the license's text."""
    metadata = dist.metadata
    if expression := (metadata.get("License-Expression") or "").strip():
        return expression
    legacy = (metadata.get("License") or "").strip()
    return legacy if legacy and "\n" not in legacy and len(legacy) <= 80 else None


def package_urls(dist: Distribution) -> dict[str, str]:
    """A package's ``Project-URL`` links by label (and the legacy
    ``Home-page``, as "Homepage"), http and https ones only: they are shown as
    links, and come from whatever package is installed."""
    metadata = dist.metadata
    pairs = [
        tuple(part.strip() for part in entry.partition(",")[::2])
        for entry in metadata.get_all("Project-URL") or ()
    ]
    if home := metadata.get("Home-page"):
        pairs.insert(0, ("Homepage", home.strip()))
    urls: dict[str, str] = {}
    for label, url in pairs:
        if label and urlsplit(url).scheme in ("http", "https"):
            urls.setdefault(label, url)
    return urls


def homepage(urls: dict[str, str]) -> str | None:
    """The link of ``urls`` (``package_urls``) to show as a package's home
    page: its Homepage, else its repository or documentation."""
    by_label = {label.lower(): url for label, url in urls.items()}
    return next((by_label[k] for k in _HOMEPAGE_LABELS if k in by_label), None)


@functools.cache
def _distribution_of(cls: type[StorageExplorerPlugin]) -> Distribution | None:
    """The installed package of ``cls``: the one registering it as a plugin,
    else the one holding its top-level package, if one does (editable
    installs, e.g. uv's, list no packages; a namespace package several fill
    names none)."""
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        if entry_point.attr == cls.__qualname__ and (
            cls.__module__ == entry_point.module
            or cls.__module__.startswith(f"{entry_point.module}.")
        ):
            return entry_point.dist
    names = set(packages_distributions().get(cls.__module__.partition(".")[0], ()))
    return distribution(names.pop()) if len(names) == 1 else None
