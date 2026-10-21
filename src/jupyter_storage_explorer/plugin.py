"""Plugins: what a package adds to every explorer (``StorageExplorerPlugin``),
found through its entry point in the group ``ENTRY_POINT_GROUP``."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport

# The entry point group plugins register their class in, named by its key.
ENTRY_POINT_GROUP = "jupyter_storage_explorer.plugins"


class StorageExplorerPlugin:
    """What a package adds to the explorer: support for an engine (e.g.
    DuckDB) or a filesystem (e.g. Azure Data Lake Storage).

    A plugin is a subclass, registered as an entry point of the group
    ``"jupyter_storage_explorer.plugins"``, named by its ``key``. Explorers load
    every plugin installed, or those their ``plugins`` argument names, and use
    what the plugin lists after what they are given and before their own
    defaults. List classes, not objects: explorers create them, without
    arguments.

    Conventions: one plugin per engine or filesystem, in a package named
    ``jupyter-storage-explorer-<name>-support``, its label "<Name> support
    for Storage Explorer". The libraries it uses are not dependencies of the
    package (shared Jupyter environments install and configure them with
    care, and a plugin must not change them): its ``full`` extra installs
    them. Import them only inside methods, as supports do.

    Attributes
    ----------
    key : str
        Identifier, the entry point's name, e.g. "duckdb-support": what
        ``StorageExplorer(plugins=[...])`` names.
    label : str
        Shown to the user, e.g. "DuckDB support for Storage Explorer".
    format_supports : sequence of FormatSupport classes
        How formats' data is handled with the plugin's engine (previews, the
        data browser, "Python code"); their formats are detected too.
    formats : sequence of DataFormat classes
        Formats of the plugin's own that none of its supports names (rare:
        a support names its format).
    filesystem_operations : sequence of FileSystemOperations classes
        File operations, tried before the default ones.
    filesystem_mappers : sequence of FileSystemMapper classes
        How the plugin's filesystems are told apart, tried before the
        default mappers.

    Examples
    --------
    In the package, the plugin:

    >>> class DuckDBSupport(StorageExplorerPlugin):
    ...     key = "duckdb-support"
    ...     label = "DuckDB support for Storage Explorer"
    ...     format_supports = [ParquetByDuckDB]

    and its entry point, in ``pyproject.toml``:

    .. code-block:: toml

        [project.entry-points."jupyter_storage_explorer.plugins"]
        duckdb-support = "jupyter_storage_explorer_duckdb_support:DuckDBSupport"
    """

    key: ClassVar[str]
    label: ClassVar[str]
    format_supports: ClassVar[Sequence[type[FormatSupport]]] = ()
    formats: ClassVar[Sequence[type[DataFormat]]] = ()
    filesystem_operations: ClassVar[Sequence[type[FileSystemOperations]]] = ()
    filesystem_mappers: ClassVar[Sequence[type[FileSystemMapper]]] = ()
