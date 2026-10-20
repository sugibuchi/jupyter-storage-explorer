"""The explorer's supports (``SupportChain``): which support of a format does
what, with which options (``format_options``), and the "Python code"
recipes they give (``Recipe``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.support import FormatSupport

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from jupyter_storage_explorer.formats import ItemContext, View, ViewLimits
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.support import (
        Capability,
        FormatOptions,
        SupportOptions,
    )
    from jupyter_storage_explorer.location import Location

# In format_options, the options of a library for all formats.
ALL_FORMATS = "*"


@dataclass(frozen=True, kw_only=True)
class Recipe:
    """One way to load the data in a notebook, e.g. as a polars LazyFrame:
    one of a support's ``recipe()`` codes, with its title and requirements
    (see ``SupportChain.recipes``)."""

    # What the code does, without the library's name, e.g. "Load as LazyFrame".
    title: str
    # The packages the code needs: the library it loads with first (its
    # support's ``engine``, which "Python code" groups recipes by), then the
    # others (``additional_requirements``); empty for Python alone.
    requirements: tuple[type[PythonPackage], ...]
    # The imports, then the loading code. Installing the packages and
    # configuring access to the storage are left to the user: reaching a data
    # lake often needs configuration that depends on it.
    code: str


class SupportChain:
    """The supports of an explorer, in order, and what is done with them: for
    each capability, the first support for the format that is installed and
    has it (see ``FormatSupport``), with its options.

    Supports given as classes are created (without arguments). Each gets an
    ``options_model`` made from ``format_options``, by library (its
    ``engine``'s package), then format name, or ``"*"`` for all formats, e.g.
    ``{"polars": {"*": {"storage_options": {...}}, "delta": {"use_pyarrow":
    True}}}``: those of its library for all formats, then for its format
    (``format.name``), each only if its model has the field. Instead of a
    dict, an entry may be a function of the item's ``Location`` returning
    one, for options depending on where the data is (e.g. an Azure
    account's credentials, by ``location.account_name``): it is called for
    each view and recipe, so keep it quick.

    ValueError for a library no support has, a format neither in
    ``format_names`` nor of a support, or an option no support of the
    library (for that format) takes: a typo would otherwise be ignored. A
    function's options are checked when it is called. TypeError for an item
    that is no FormatSupport.
    """

    def __init__(
        self,
        supports: Iterable[type[FormatSupport] | FormatSupport],
        format_options: FormatOptions | None = None,
        *,
        format_names: Sequence[str] = (),
    ) -> None:
        self.supports = [_created(s) for s in supports]
        self.format_options = format_options or {}
        # The supports of each library, and the format names options may
        # name: what options are checked against.
        self._libraries: dict[str, list[FormatSupport]] = {}
        for support in self.supports:
            if support.engine is not None:
                self._libraries.setdefault(support.library(), []).append(support)
        self._format_names = list(
            dict.fromkeys([*format_names, *(s.format.name for s in self.supports)])
        )
        _check_options(self.format_options, self._libraries, self._format_names)

    def options_of(self, support: FormatSupport, location: Location) -> SupportOptions:
        """The options of ``support`` for the item at ``location``: those of
        its library for all formats, then for its format, those its model
        has (see the class docstring). ValueError for options a function
        returned that no support of the library takes."""
        library = support.library()
        by_format = self.format_options.get(library, {}) if support.engine else {}
        merged: dict[str, Any] = {}
        for name in (ALL_FORMATS, support.format.name):
            values = by_format.get(name)
            if callable(values):
                values = values(location)
                _check_format_options(
                    f"format_options[{library!r}][{name!r}]({location.url!r})",
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

    def view(self, fmt: DataFormat, ctx: ItemContext, limits: ViewLimits) -> View:
        """The view of the first support of ``of(fmt, "view")`` that views the
        item (see ``FormatSupport.view``). ValueError if each of them refuses
        it (``NotSupported``); RuntimeError if there is none: callers check
        ``of`` first."""
        supports = self.of(fmt, "view")
        if not supports:
            raise RuntimeError(
                f"no support installed views {fmt.label}; check of() first"
            )
        for support in supports:
            options = self.options_of(support, ctx.location)
            try:
                return support.view(fmt, ctx, options, limits)
            except FormatSupport.NotSupported:
                continue
        raise ValueError(f"{ctx.name} cannot be viewed as {fmt.label}")

    def recipes(self, fmt: DataFormat, ctx: ItemContext) -> list[Recipe]:
        """The recipes of the supports with "recipe" for ``fmt``, installed or
        not (the code may run elsewhere): of each library, those of the first
        support that has code for the item, so a support given before the
        defaults replaces the default one of its library."""
        recipes: list[Recipe] = []
        libraries: set[str] = set()
        for support in self._registered(fmt, "recipe"):
            if support.library() in libraries:
                continue
            options = self.options_of(support, ctx.location)
            try:
                codes = support.recipe(fmt, ctx, options)
            except FormatSupport.NotSupported:
                continue
            libraries.add(support.library())
            recipes += [
                Recipe(title=title, requirements=support.requirements(), code=code)
                for title, code in codes.items()
            ]
        return recipes


def _created(support: type[FormatSupport] | FormatSupport) -> FormatSupport:
    """``support``, created if it is a class. TypeError if it is no FormatSupport."""
    cls = support if isinstance(support, type) else type(support)
    if not issubclass(cls, FormatSupport):
        raise TypeError(f"not a FormatSupport: {support!r}")
    return support() if isinstance(support, type) else support


def _check_options(
    format_options: Mapping[str, Any],
    libraries: Mapping[str, Sequence[FormatSupport]],
    format_names: Sequence[str],
) -> None:
    """ValueError for ``format_options`` that no support takes (see
    ``SupportChain``); functions are checked when called."""
    for library, by_format in format_options.items():
        if library not in libraries:
            raise ValueError(
                f"format_options: unknown library {library!r}; "
                f"choose from {sorted(libraries)}"
            )
        if not isinstance(by_format, dict):
            raise ValueError(
                f"format_options[{library!r}] must be a dict of format names "
                f"(or {ALL_FORMATS!r}) to options"
            )
        for name, values in by_format.items():
            _check_format_options(
                f"format_options[{library!r}][{name!r}]",
                name,
                values,
                libraries[library],
                format_names,
            )


def _check_format_options(
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
