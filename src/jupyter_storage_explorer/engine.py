"""The engines handling formats' data: the ``Engine`` interface (python.py
has ``PythonEngine``, the built-in actions'; plugins define the others), and
``EngineOptions``, the type of the engines' options, ``engine_options``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

# At run time, not only for type checkers: EngineOptions, a public alias,
# names it.
from jupyter_storage_explorer.base import Location

if TYPE_CHECKING:
    from jupyter_storage_explorer.packages import PythonPackage

# StorageExplorer's engine_options: {engine key: {format name or "*": options}},
# the options a dict, or a function of the item's location returning one
# (see StorageExplorer's engine_options).
EngineOptions: TypeAlias = Mapping[
    str, Mapping[str, Mapping[str, Any] | Callable[[Location], Mapping[str, Any]]]
]


class Engine:
    """A library viewing and loading data, e.g. polars or PySpark: what an
    action uses (its ``engine``), and what users choose in the explorer (its
    settings menu, "Preview as").

    Explorers collect the engines of their actions. Those installed that
    view something are offered, in the order of ``engine_preference``
    (see ``StorageExplorer``), then by ``key``.

    Attributes
    ----------
    key : str
        Identifier, lower case, e.g. "polars": in ``engine_preference``, and
        the key of its actions' options in ``engine_options``.
    label : str
        Shown to the user, e.g. "Polars".
    requirements : tuple of PythonPackage
        The packages it needs, all of them, e.g. ``(Polars(),)``. Empty for
        none.

    Examples
    --------
    >>> class DuckDBEngine(Engine):
    ...     key = "duckdb"
    ...     label = "DuckDB"
    ...     requirements = (DuckDB(),)
    """

    key: ClassVar[str]
    label: ClassVar[str]
    requirements: ClassVar[tuple[PythonPackage, ...]] = ()

    @classmethod
    def is_installed(cls) -> bool:
        """Whether its packages are all installed."""
        return all(p.is_installed() for p in cls.requirements)
