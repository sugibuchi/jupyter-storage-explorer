"""The engines handling formats' data: the ``Engine`` interface (python.py
has ``PythonEngine``, the built-in actions'; plugins define the others),
``EngineOptions``, the type of the engines' options, ``engine_options``, and
``by_protocol``, options that depend on the storage."""

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

# Options in engine_options: a dict, or a function of the item's location.
_Options: TypeAlias = Mapping[str, Any] | Callable[[Location], Mapping[str, Any]]

# The key of the options for every protocol, as "*" is for every format.
_ALL_PROTOCOLS = "*"


def by_protocol(
    options: Mapping[str, _Options],
) -> Callable[[Location], dict[str, Any]]:
    """Options that depend on the storage, by the protocol of the item's URL.

    Give the function returned in ``engine_options`` in place of a dict of
    options, for one format or ``"*"``.

    Parameters
    ----------
    options : mapping
        Protocol -> options. A protocol is that of the item's location
        (``Location.protocol``): ``"abfs"``, ``"s3"``, ``"gs"``, ``"sftp"``,
        ``"file"``, ``"memory"``, ``"dbfs"`` or another storage's. ``"*"``
        gives the options of every protocol, which a protocol's own
        override. Each options is a dict, or a function of the item's
        location returning one.

    Returns
    -------
    callable
        A function of the item's location returning its options: none for a
        protocol not given, without ``"*"``.

    Raises
    ------
    ValueError
        When the explorer is created, for an option no action of the engine
        takes. A function's options are checked when it is called.

    Examples
    --------
    >>> StorageExplorer(
    ...     "abfs://lake@account.dfs.core.windows.net",
    ...     engine_options={
    ...         "polars": {
    ...             "*": by_protocol({
    ...                 "abfs": {"credential_provider": pl.CredentialProviderAzure()},
    ...                 "s3": {"credential_provider": pl.CredentialProviderAWS(profile_name="personal")},
    ...             }),
    ...         },
    ...     },
    ... )
    """
    return _ByProtocol(dict(options))


class _ByProtocol:
    """What ``by_protocol`` returns: a function of the location, which keeps
    its options so that the explorer checks the dicts when it is created."""

    def __init__(self, options: dict[str, _Options]) -> None:
        self.options = options

    def __call__(self, location: Location) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in (_ALL_PROTOCOLS, location.protocol):
            values = self.options.get(key)
            if callable(values):
                values = values(location)
            merged.update(values or {})
        return merged

    def __repr__(self) -> str:
        return f"by_protocol({self.options!r})"


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
