"""Plugins: what a package adds to every explorer (``StorageExplorerPlugin``),
found through its entry point in the group ``ENTRY_POINT_GROUP``, and their
options (``StorageExplorerPluginOptions``)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport

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
        Plugins of a higher priority come first: their supports, operations
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
    ``jupyter-storage-explorer-<name>-support``, its label "<Name> support
    for Storage Explorer". The libraries it uses are not dependencies of the
    package (shared Jupyter environments install and configure them with
    care, and a plugin must not change them): its ``full`` extra installs
    them. Import them only inside methods, as supports do.

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
    label : str
        Shown to the user, e.g. "DuckDB support for Storage Explorer".
    options_model : type, default StorageExplorerPluginOptions
        The class of its options: a frozen, keyword-only dataclass
        subclassing ``StorageExplorerPluginOptions``, each field with a
        default.
    options : StorageExplorerPluginOptions
        Its options, for the properties to make its components with.
    format_supports : sequence of FormatSupport classes or objects
        How formats' data is handled with the plugin's engine (previews, the
        data browser, "Python code"); their formats are detected too.
    formats : sequence of DataFormat classes
        Formats of the plugin's own that none of its supports names (rare:
        a support names its format).
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
    ...     threads: int = 4
    >>> class DuckDBSupport(StorageExplorerPlugin):
    ...     key = "duckdb-support"
    ...     label = "DuckDB support for Storage Explorer"
    ...     options_model = DuckDBSupportOptions
    ...
    ...     @property
    ...     def format_supports(self):
    ...         return (ParquetByDuckDB(threads=self.options.threads),)

    its entry point, in ``pyproject.toml``:

    .. code-block:: toml

        [project.entry-points."jupyter_storage_explorer.plugins"]
        duckdb-support = "jupyter_storage_explorer_duckdb_support:DuckDBSupport"

    and an explorer giving it options, and disabling another plugin:

    >>> StorageExplorer(plugin_options={
    ...     "duckdb-support": {"threads": 8, "priority": 10},
    ...     "pandas-support": {"enabled": False},
    ... })
    """

    key: ClassVar[str]
    label: ClassVar[str]
    options_model: ClassVar[type[StorageExplorerPluginOptions]] = (
        StorageExplorerPluginOptions
    )

    def __init__(self, options: StorageExplorerPluginOptions | None = None) -> None:
        self.options = options if options is not None else self.options_model()

    @property
    def format_supports(self) -> Sequence[type[FormatSupport] | FormatSupport]:
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
