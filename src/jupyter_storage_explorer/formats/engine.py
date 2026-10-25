"""The engines handling formats' data: the ``Engine`` interface, and
``PythonEngine``, the built-in actions' (plugins define the others)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.package import PythonPackage


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


class PythonEngine(Engine):
    """Python alone, with the explorer's own packages: the engine of the
    built-in actions (text, Markdown, JSON and images). Explorers offer it
    in no menu: its views are those of formats no engine chosen handles.
    Its actions' options are ``engine_options["python"]``."""

    key = "python"
    label = "Python"
    requirements = ()
