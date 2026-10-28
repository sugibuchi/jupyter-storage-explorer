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
    from collections.abc import Iterable

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


def _merged_engine_options(layers: Iterable[EngineOptions]) -> dict[str, Any]:
    """Several ``engine_options`` as one, each layer over those before: by
    engine, format, then option, so that a layer changes one option of a
    format without restating the others. The plugins' and the launcher's
    files' layers are merged so. Whether the names exist is checked by the
    explorer."""
    merged: dict[str, Any] = {}
    for layer in layers:
        for key, by_format in layer.items():
            if not isinstance(by_format, Mapping):
                # Not merged, e.g. a typo: the explorer's check reports it.
                merged[key] = by_format
                continue
            formats = merged.get(key)
            if not isinstance(formats, dict):
                formats = merged[key] = {}
            for name, options in by_format.items():
                formats[name] = _merged_options(formats.get(name), options)
    return merged


def _merged_options(earlier: Any, later: Any) -> Any:
    """A later layer's options of a format over an earlier layer's, option by
    option: a dict while both are dicts, else a function of the location
    (as either may be) giving the earlier's options updated with the
    later's.

    Dicts and ``by_protocol``s merge into a ``by_protocol``, so that the
    explorer still checks their dicts when it is created: a dict is then
    the options of every protocol."""
    if earlier is None:
        return dict(later) if isinstance(later, Mapping) else later
    if isinstance(earlier, Mapping) and isinstance(later, Mapping):
        return {**earlier, **later}
    if all(isinstance(o, (Mapping, _ByProtocol)) for o in (earlier, later)):
        return by_protocol(
            _merged_by_protocol(_protocols_of(earlier), _protocols_of(later))
        )

    def options(location: Location) -> dict[str, Any]:
        return {**_options_at(earlier, location), **_options_at(later, location)}

    return options


def _protocols_of(options: Any) -> dict[str, Any]:
    """A dict or ``by_protocol``'s options by protocol, "*" for every one."""
    return (
        {_ALL_PROTOCOLS: options} if isinstance(options, Mapping) else options.options
    )


def _merged_by_protocol(
    earlier: dict[str, Any], later: dict[str, Any]
) -> dict[str, Any]:
    """Two layers' options by protocol as one. A protocol's are those of
    every protocol, then its own, of the earlier layer, then the same of
    the later: the later's "*" still overrides the earlier's protocol."""
    merged = {}
    for protocol in dict.fromkeys([*earlier, *later]):
        parts = [earlier.get(_ALL_PROTOCOLS), later.get(_ALL_PROTOCOLS)]
        if protocol != _ALL_PROTOCOLS:
            parts = [parts[0], earlier.get(protocol), parts[1], later.get(protocol)]
        result = None
        for part in parts:
            if part is not None:
                result = _merged_options(result, part)
        merged[protocol] = result
    return merged


def _options_at(options: Any, location: Location) -> dict[str, Any]:
    """``options``, or what the function ``options`` gives for ``location``."""
    return dict(options(location) if callable(options) else options)


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
