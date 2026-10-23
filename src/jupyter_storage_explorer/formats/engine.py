"""The engines handling formats' data: the ``Engine`` interface (engines.py
has the predefined ones)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.package import PythonPackage


class Engine:
    """A library viewing and loading data, e.g. polars or PySpark: what a
    support uses (``FormatSupport.engine``), and what users choose in the
    explorer (its settings menu, "Preview as").

    Explorers collect the engines of their supports. Those installed that
    view something are offered, in the order of ``engine_preference``
    (see ``StorageExplorer``), then by ``key``.

    Attributes
    ----------
    key : str
        Identifier, lower case, e.g. "polars": in ``engine_preference``, and
        the key of its supports' options in ``engine_options``.
    label : str
        Shown to the user, e.g. "Polars".
    requirements : tuple
        The packages it needs, as ``PythonPackage`` instances: a tuple of
        them, all needed, e.g. ``(Polars(),)``; or a tuple of such tuples,
        alternatives, the first installed one used, e.g. ``((PySpark(),),
        (DatabricksConnect(),))``. Empty for none.

    Examples
    --------
    >>> class DuckDBEngine(Engine):
    ...     key = "duckdb"
    ...     label = "DuckDB"
    ...     requirements = (DuckDB(),)
    """

    key: ClassVar[str]
    label: ClassVar[str]
    requirements: ClassVar[
        tuple[PythonPackage, ...] | tuple[tuple[PythonPackage, ...], ...]
    ] = ()

    @classmethod
    def alternatives(cls) -> tuple[tuple[PythonPackage, ...], ...]:
        """The sets of packages it can run with, in order of preference: one
        for ``requirements`` of packages, each for one of tuples."""
        requirements = cls.requirements
        if requirements and all(isinstance(r, tuple) for r in requirements):
            return tuple(requirements)  # type: ignore[arg-type]
        return (tuple(requirements),)  # type: ignore[arg-type]

    @classmethod
    def packages(cls) -> tuple[PythonPackage, ...]:
        """The packages it runs with: the first alternative installed, else
        the first (e.g. to name them under code meant to run elsewhere)."""
        alternatives = cls.alternatives()
        for packages in alternatives:
            if all(p.is_installed() for p in packages):
                return packages
        return alternatives[0]

    @classmethod
    def is_installed(cls) -> bool:
        """Whether the packages of one of its alternatives are all installed."""
        return any(
            all(p.is_installed() for p in packages) for packages in cls.alternatives()
        )
