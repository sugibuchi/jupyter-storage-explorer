"""The explorer's supports (``SupportChain``): the formats they handle, which
support of a format does what, with which engine and options
(``engine_options``), the engines users choose from, and the "Python code"
recipes the supports give (``Recipe``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.support import FormatSupport

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from jupyter_storage_explorer.formats import ItemContext, View, ViewLimits
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.engine import Engine
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.support import (
        Capability,
        EngineOptions,
        SupportOptions,
    )
    from jupyter_storage_explorer.location import Location

# In engine_options, the options of a library for all formats.
ALL_FORMATS = "*"

# The engines offered first when the explorer is given no engine_preference:
# polars queries the data itself, lazily; pandas reads it whole, so only its
# first rows. Others (e.g. PySpark) follow by key.
DEFAULT_ENGINE_PREFERENCE = ("polars", "pandas")


def engine_key(support: FormatSupport) -> str | None:
    """The key of a support's engine; None for the built-in views."""
    return support.engine.key if support.engine is not None else None


@dataclass(frozen=True, kw_only=True)
class Recipe:
    """One way to load the data in a notebook, e.g. as a polars LazyFrame:
    one of a support's ``recipe()`` codes, with its title, engine and
    requirements (see ``SupportChain.recipes``)."""

    # What the code does, without the library's name, e.g. "Load as LazyFrame".
    title: str
    # The engine it loads with, which "Python code" names; None for none.
    engine: type[Engine] | None
    # The packages the code needs: its engine's, then the support's others
    # (``additional_requirements``); empty for Python alone.
    requirements: tuple[PythonPackage, ...]
    # The imports, then the loading code. Installing the packages and
    # configuring access to the storage are left to the user: reaching a data
    # lake often needs configuration that depends on it.
    code: str


class SupportChain:
    """The supports of an explorer, in order, and what is done with them: for
    each capability, the first support for the format that is installed and
    has it (see ``FormatSupport``), of the engine asked for, with its
    options.

    Supports given as classes are created (without arguments). Each gets an
    ``options_model`` made from ``engine_options``, by engine key ("python"
    for the supports without an engine: the built-in views and code), then
    format name, or ``"*"`` for all formats, e.g. ``{"polars": {"*":
    {"storage_options": {...}}, "delta": {"use_pyarrow": True}}}``: those of
    its engine for all formats, then for its format (``format.name``), each
    only if its model has the field. Instead of a dict, an entry may be a
    function of the item's ``Location`` returning one, for options depending
    on where the data is (e.g. an Azure account's credentials, by
    ``location.account_name``): it is called for each view and recipe, so
    keep it quick.

    ``formats`` are the formats files are detected as: one of each
    ``format`` of the supports, in their order (on a tie in priority, the
    first wins: those of supports given before the defaults), then of the
    format classes given as ``formats`` (the standard ones, detected even
    without a support installed, and plugins' own).

    ``engines`` are those users choose from: the supports' engines that are
    installed and view something, those of ``engine_preference`` (keys)
    first, in its order, then the others by key. Without one,
    ``DEFAULT_ENGINE_PREFERENCE``.

    ValueError for an engine key no support has (in ``engine_preference``
    or ``engine_options``), two engine classes of one key (an engine is
    defined once, e.g. by its plugin, and imported by others), a format of
    no support, or an option no support of the engine (for that format) takes:
    a typo would otherwise be ignored. A function's options are checked when
    it is called. TypeError for an item that is no FormatSupport.
    """

    def __init__(
        self,
        supports: Iterable[type[FormatSupport] | FormatSupport],
        engine_options: EngineOptions | None = None,
        *,
        formats: Iterable[type[DataFormat]] = (),
        engine_preference: Sequence[str] | None = None,
    ) -> None:
        self.supports = [_created(s) for s in supports]
        self.engine_options = engine_options or {}
        # The supports of each library (an engine's key, or "python"), and
        # the format names options may name: what options are checked against.
        self._libraries: dict[str, list[FormatSupport]] = {}
        for support in self.supports:
            self._libraries.setdefault(support.library(), []).append(support)
        engine_keys = {s.engine.key for s in self.supports if s.engine is not None}
        # One object of each format: formats keep what detection finds (e.g.
        # a Parquet dataset's layout) for their supports.
        self.formats: list[DataFormat] = [
            cls()
            for cls in dict.fromkeys([*(s.format for s in self.supports), *formats])
        ]
        self._format_names = [f.name for f in self.formats]
        _check_options(self.engine_options, self._libraries, self._format_names)
        if engine_preference is None:
            engine_preference = DEFAULT_ENGINE_PREFERENCE
        else:
            unknown = [k for k in engine_preference if k not in engine_keys]
            if unknown:
                raise ValueError(
                    f"engine_preference: unknown engines {unknown}; "
                    f"choose from {sorted(engine_keys)}"
                )
        _check_engine_keys(self.supports)
        self.engines = _ordered_engines(self.supports, engine_preference)
        self._engine_preference = list(engine_preference)

    def options_of(self, support: FormatSupport, location: Location) -> SupportOptions:
        """The options of ``support`` for the item at ``location``: those of
        its library for all formats, then for its format, those its model
        has (see the class docstring). ValueError for options a function
        returned that no support of the library takes."""
        library = support.library()
        by_format = self.engine_options.get(library, {})
        merged: dict[str, Any] = {}
        for name in (ALL_FORMATS, support.format.name):
            values = by_format.get(name)
            if callable(values):
                values = values(location)
                _check_engine_options(
                    f"engine_options[{library!r}][{name!r}]({location.url!r})",
                    name,
                    values,
                    self._libraries[library],
                    self._format_names,
                )
            merged.update(values or {})
        taken = support.options_model.option_names()
        return support.options_model(**{k: v for k, v in merged.items() if k in taken})

    def _registered(
        self, fmt: DataFormat, capability: Capability
    ) -> list[FormatSupport]:
        """The supports for ``fmt`` with ``capability``, installed or not, in
        order."""
        return [
            s
            for s in self.supports
            if isinstance(fmt, s.format) and capability in s.capabilities
        ]

    def of(self, fmt: DataFormat, capability: Capability) -> list[FormatSupport]:
        """The supports for ``fmt`` (an instance of their ``format``) with
        ``capability`` whose packages are installed, in order: those the
        explorer may call. Empty if none of the supports can."""
        return [s for s in self._registered(fmt, capability) if s.is_installed()]

    def viewers(self, fmt: DataFormat) -> list[str | None]:
        """The engines that can view ``fmt`` (their supports installed), in
        the order of ``engines``, then None if the built-in views can: for
        "Preview as"."""
        keys = {engine_key(s) for s in self.of(fmt, "view")}
        return [e.key for e in self.engines if e.key in keys] + (
            [None] if None in keys else []
        )

    def engine_for(self, fmt: DataFormat, engine: str | None) -> str | None:
        """The engine viewing ``fmt`` when ``engine`` is chosen: that engine,
        if it handles the format; else, for a format it does not handle at
        all (e.g. Markdown for polars), None for the built-in views. LookupError
        if neither can view it: an engine handling the format does not leave
        it to another (the user picks one in "Preview as")."""
        registered = self._registered(fmt, "view")
        if any(engine_key(s) == engine for s in registered):
            if any(engine_key(s) == engine for s in self.of(fmt, "view")):
                return engine
        elif any(engine_key(s) is None for s in self.of(fmt, "view")):
            return None
        raise LookupError(engine)

    def view(
        self, fmt: DataFormat, ctx: ItemContext, limits: ViewLimits, engine: str | None
    ) -> View:
        """The view of the first support of ``engine`` (a key; None for the
        built-in views) installed for ``fmt`` that views the item (see
        ``FormatSupport.view``). ValueError if each of them refuses it
        (``NotSupported``); RuntimeError if there is none: callers check
        ``viewers`` or ``engine_for`` first."""
        supports = [s for s in self.of(fmt, "view") if engine_key(s) == engine]
        if not supports:
            raise RuntimeError(
                f"no support of {engine or 'the built-in views'} installed views "
                f"{fmt.label}; check viewers() first"
            )
        for support in supports:
            options = self.options_of(support, ctx.location)
            try:
                return support.view(fmt, ctx, options, limits)
            except FormatSupport.NotSupported:
                continue
        raise ValueError(f"{ctx.name} cannot be viewed as {fmt.label}")

    def recipes(self, fmt: DataFormat, ctx: ItemContext) -> list[Recipe]:
        """The recipes of the supports with "recipe" for ``fmt`` whose packages
        are installed, as for views: code the kernel could not run is not
        offered. Of each engine, those of the first support that has code for
        the item, so a support given before the defaults replaces the default
        one of its engine. Those without an engine first, then by engine:
        those of ``engine_preference``, in its order, then the others by key,
        whichever plugin they come from."""
        recipes: list[Recipe] = []
        libraries: set[str] = set()
        for support in self.of(fmt, "recipe"):
            if support.library() in libraries:
                continue
            options = self.options_of(support, ctx.location)
            try:
                codes = support.recipe(fmt, ctx, options)
            except FormatSupport.NotSupported:
                continue
            libraries.add(support.library())
            recipes += [
                Recipe(
                    title=title,
                    engine=support.engine,
                    requirements=support.requirements(),
                    code=code,
                )
                for title, code in codes.items()
            ]
        order = {key: i for i, key in enumerate(self._engine_preference)}

        def rank(recipe: Recipe) -> tuple[int, int, str]:
            if recipe.engine is None:
                return (0, 0, "")
            return (1, order.get(recipe.engine.key, len(order)), recipe.engine.key)

        return sorted(recipes, key=rank)


def _created(support: type[FormatSupport] | FormatSupport) -> FormatSupport:
    """``support``, created if it is a class. TypeError if it is no FormatSupport."""
    cls = support if isinstance(support, type) else type(support)
    if not issubclass(cls, FormatSupport):
        raise TypeError(f"not a FormatSupport: {support!r}")
    return support() if isinstance(support, type) else support


def _check_options(
    engine_options: Mapping[str, Any],
    libraries: Mapping[str, Sequence[FormatSupport]],
    format_names: Sequence[str],
) -> None:
    """ValueError for ``engine_options`` that no support takes (see
    ``SupportChain``); functions are checked when called."""
    for library, by_format in engine_options.items():
        if library not in libraries:
            raise ValueError(
                f"engine_options: unknown engine {library!r}; "
                f"choose from {sorted(libraries)}"
            )
        if not isinstance(by_format, dict):
            raise ValueError(
                f"engine_options[{library!r}] must be a dict of format names "
                f"(or {ALL_FORMATS!r}) to options"
            )
        for name, values in by_format.items():
            _check_engine_options(
                f"engine_options[{library!r}][{name!r}]",
                name,
                values,
                libraries[library],
                format_names,
            )


def _check_engine_options(
    where: str,
    name: str,
    values: Any,
    supports: Sequence[FormatSupport],
    format_names: Sequence[str],
) -> None:
    """ValueError for options of a library for format ``name`` (or all) that
    none of its ``supports`` for it takes."""
    if name != ALL_FORMATS and name not in format_names:
        raise ValueError(
            f"{where}: unknown format; choose from {[ALL_FORMATS, *format_names]}"
        )
    if callable(values):
        return  # checked when called, by SupportChain.options_of
    if not isinstance(values, dict):
        raise ValueError(f"{where} must be a dict of options")
    taken: set[str] = set()
    for support in supports:
        if name in (ALL_FORMATS, support.format.name):
            taken |= support.options_model.option_names()
    unknown = values.keys() - taken
    if unknown:
        raise ValueError(
            f"{where}: unknown options {sorted(unknown)}; choose from {sorted(taken)}"
        )


def _check_engine_keys(supports: Sequence[FormatSupport]) -> None:
    """ValueError for two engine classes of one key: supports of an engine
    share its class, so that the explorer offers it once, with one label."""
    engines: dict[str, type[Engine]] = {}
    for support in supports:
        engine = support.engine
        if engine is None:
            continue
        known = engines.setdefault(engine.key, engine)
        if known is not engine:
            raise ValueError(
                f"engine {engine.key!r} is defined twice: by "
                f"{known.__module__}.{known.__qualname__} and "
                f"{engine.__module__}.{engine.__qualname__}; import one"
            )


def _ordered_engines(
    supports: Sequence[FormatSupport], preference: Sequence[str]
) -> list[type[Engine]]:
    """The engines of ``supports`` users choose from: installed, viewing
    something (a support of theirs with "view" installed), ``preference``'s
    first, in its order, then the others by key."""
    engines: dict[str, type[Engine]] = {}
    for support in supports:
        engine = support.engine
        if (
            engine is not None
            and "view" in support.capabilities
            and support.is_installed()
        ):
            engines.setdefault(engine.key, engine)
    first = [engines[k] for k in dict.fromkeys(preference) if k in engines]
    rest = sorted((e for e in engines.values() if e not in first), key=lambda e: e.key)
    return first + rest
