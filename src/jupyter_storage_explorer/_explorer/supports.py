"""The explorer's actions (``ActionChain``): the formats they handle, which
action does what to an item, with which engine and options
(``engine_options``), the engines users choose from, and the "Python code"
recipes the code actions give (``Recipe``).

Supports of the former interface, ``FormatSupport`` classes or objects, are
turned into actions here (``_adapted``), until the plugins are written with
actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer.formats.actions import (
    Action,
    CodeAction,
    ViewAction,
    check_actions,
)
from jupyter_storage_explorer.formats.support import FormatSupport

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from jupyter_storage_explorer.formats import ItemContext, View, ViewLimits
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.engine import Engine
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.support import EngineOptions, SupportOptions
    from jupyter_storage_explorer.location import Location

# In engine_options, the options of a library for all formats.
ALL_FORMATS = "*"

# The engines offered first when the explorer is given no engine_preference:
# polars queries the data itself, lazily; pandas reads it whole, so only its
# first rows. Others (e.g. PySpark) follow by key.
DEFAULT_ENGINE_PREFERENCE = ("polars", "pandas")

# What explorers give their actions as: actions, or supports of the former
# interface (classes or objects), turned into actions.
ActionLike = Action[Any] | FormatSupport | type[FormatSupport]


def engine_key(action: Action[Any]) -> str | None:
    """The key of an action's engine; None for the built-in views."""
    return action.engine.key if action.engine is not None else None


@dataclass(frozen=True, kw_only=True)
class Recipe:
    """One way to load the data in a notebook, e.g. as a polars LazyFrame:
    the code of a code action, with its title, engine and requirements (see
    ``ActionChain.recipes``)."""

    # What the code does, without the library's name, e.g. "Load as LazyFrame".
    title: str
    # The engine it loads with, which "Python code" names; None for none.
    engine: type[Engine] | None
    # The packages the code needs: its engine's, then the action's others
    # (``requires``); empty for Python alone.
    requirements: tuple[PythonPackage, ...]
    # The imports, then the loading code. Installing the packages and
    # configuring access to the storage are left to the user: reaching a data
    # lake often needs configuration that depends on it.
    code: str
    # Why the action failed, shown in place of the code (then empty); "" if
    # it did not.
    error: str = ""


@dataclass(frozen=True, eq=False)
class _AdaptedView(ViewAction):
    """The view of a ``FormatSupport``, as an action."""

    support: FormatSupport | None = None


@dataclass(frozen=True, eq=False)
class _AdaptedCode(CodeAction):
    """The recipes of a ``FormatSupport``, as an action whose function
    returns several, by title."""

    support: FormatSupport | None = None


def _created(support: FormatSupport | type[FormatSupport]) -> FormatSupport:
    """``support``, created if it is a class. TypeError if it is no action
    and no FormatSupport."""
    cls = support if isinstance(support, type) else type(support)
    if not issubclass(cls, FormatSupport):
        raise TypeError(f"not an action nor a FormatSupport: {support!r}")
    return support() if isinstance(support, type) else support


def _adapted(created: FormatSupport) -> list[Action[Any]]:
    """``created``'s view and recipes as actions."""
    cls = type(created)
    common: dict[str, Any] = {
        "format": cls.format,
        "engine": cls.engine,
        # As the menu shows it if the engine has other views. Supports have no
        # names: adapted actions are left out of check_actions, and only the
        # first of an engine counts (see view_names).
        "name": f"View {cls.format.label}",
        "requires": tuple(cls.additional_requirements),
        "options_model": cls.options_model,
        "support": created,
    }
    actions: list[Action[Any]] = []
    if cls.implements("view"):
        actions.append(
            _AdaptedView(
                function=created.view,
                check=lambda fmt, ctx, options: created.supports(
                    fmt, ctx, options, "view"
                ),
                **common,
            )
        )
    if cls.implements("recipe"):
        actions.append(
            _AdaptedCode(
                function=created.recipe,
                check=lambda fmt, ctx, options: created.supports(
                    fmt, ctx, options, "recipe"
                ),
                **common,
            )
        )
    return actions


# Something with options of a format and a library: an action, or a support
# of the former interface (whose library() is a method).
_WithOptions = Action[Any] | FormatSupport


def _library(item: _WithOptions) -> str:
    return item.library if isinstance(item, Action) else item.library()


class ActionChain:
    """The actions of an explorer, in order, and what is done with them: for
    an item, the actions of its format that are installed and whose check
    agrees, of the engine asked for, with their options. The first such
    view is the item's default.

    Each action gets an ``options_model`` made from ``engine_options``, by
    engine key ("python" for the actions without an engine: the built-in
    views and code), then format name, or ``"*"`` for all formats, e.g.
    ``{"polars": {"*": {"storage_options": {...}}, "delta": {"use_pyarrow":
    True}}}``: those of its engine for all formats, then for its format
    (``format.name``), each only if its model has the field. Instead of a
    dict, an entry may be a function of the item's ``Location`` returning
    one, for options depending on where the data is (e.g. an Azure account's
    credentials, by ``location.account_name``): it is called for each view
    and recipe, so keep it quick.

    ``formats`` are the formats files are detected as: one of each
    ``format`` of the actions, in their order (on a tie in priority, the
    first wins: those of actions given before the defaults), then of the
    format classes given as ``formats`` (the standard ones, detected even
    without an action installed, and plugins' own).

    ``engines`` are those users choose from: the actions' engines that are
    installed and view something, those of ``engine_preference`` (keys)
    first, in its order, then the others by key. Without one,
    ``DEFAULT_ENGINE_PREFERENCE``.

    ValueError for an engine key no action has (in ``engine_preference``
    or ``engine_options``), two engine classes of one key (an engine is
    defined once, e.g. by its plugin, and imported by others), two format
    classes of one name, a format of no action, an option no action of the
    engine (for that format) takes: a typo would otherwise be ignored; and
    actions that cannot be used together (``formats.actions.check_actions``).
    A function's options are checked when it is called. TypeError for an
    item that is no action.
    """

    def __init__(
        self,
        actions: Iterable[ActionLike],
        engine_options: EngineOptions | None = None,
        *,
        formats: Iterable[type[DataFormat]] = (),
        engine_preference: Sequence[str] | None = None,
    ) -> None:
        self.actions: list[Action[Any]] = []
        # The supports of the former interface given, created; their formats
        # and options count even if they implement nothing.
        self.supports: list[FormatSupport] = []
        given: list[_WithOptions] = []
        for item in actions:
            if isinstance(item, Action):
                self.actions.append(item)
                given.append(item)
            else:
                created = _created(item)
                self.supports.append(created)
                self.actions += _adapted(created)
                given.append(created)
        self.engine_options = engine_options or {}
        # What takes options, by library (an engine's key, or "python"): what
        # options are checked against.
        self._libraries: dict[str, list[_WithOptions]] = {}
        for item in given:
            self._libraries.setdefault(_library(item), []).append(item)
        engine_keys = {a.engine.key for a in given if a.engine is not None}
        # One object of each format: formats keep what detection finds (e.g.
        # a Parquet dataset's layout) for their actions.
        self.formats: list[DataFormat] = [
            cls() for cls in dict.fromkeys([*(a.format for a in given), *formats])
        ]
        self._format_names = [f.name for f in self.formats]
        _check_format_names(self.formats)
        check_actions([a for a in self.actions if not _is_adapted(a)])
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
        _check_engine_keys(given)
        self.engines = _ordered_engines(self.actions, engine_preference)
        self._engine_preference = list(engine_preference)

    def libraries(self) -> set[str]:
        """The keys of the actions' libraries: their engines', "python" for
        those without one."""
        return set(self._libraries)

    def options_of(self, action: _WithOptions, location: Location) -> SupportOptions:
        """The options of ``action`` for the item at ``location``: those of
        its library for all formats, then for its format, those its model
        has (see the class docstring). ValueError for options a function
        returned that no action of the library takes."""
        library = _library(action)
        by_format = self.engine_options.get(library, {})
        merged: dict[str, Any] = {}
        for name in (ALL_FORMATS, action.format.name):
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
        taken = action.options_model.option_names()
        return action.options_model(**{k: v for k, v in merged.items() if k in taken})

    def _registered(
        self, fmt: DataFormat, kind: type[Action[Any]]
    ) -> list[Action[Any]]:
        """The actions of ``kind`` for ``fmt``, installed or not, whatever the
        item, in order."""
        return [
            a for a in self.actions if isinstance(fmt, a.format) and isinstance(a, kind)
        ]

    def installed(self, fmt: DataFormat, kind: type[Action[Any]] = ViewAction) -> bool:
        """Whether an action of ``kind`` for ``fmt`` is installed, whatever the
        item."""
        return any(a.is_installed() for a in self._registered(fmt, kind))

    def of(
        self, fmt: DataFormat, ctx: ItemContext, kind: type[Action[Any]] = ViewAction
    ) -> list[Action[Any]]:
        """The actions of ``kind`` for ``fmt`` (an instance of their
        ``format``) whose packages are installed and that do the item, with
        their options for it, in order: those the explorer may call. Empty if
        none of them can."""
        return [
            a
            for a in self._registered(fmt, kind)
            if a.is_installed() and a.does(fmt, ctx, self.options_of(a, ctx.location))
        ]

    def viewers(self, fmt: DataFormat, ctx: ItemContext) -> list[str | None]:
        """The engines that can view the item as ``fmt`` (their actions
        installed, and doing it), in the order of ``engines``, then None if
        the built-in views can: for "Preview as"."""
        return list(self.views_by_engine(fmt, ctx))

    def views_by_engine(
        self, fmt: DataFormat, ctx: ItemContext
    ) -> dict[str | None, list[str]]:
        """The names of the view actions doing the item as ``fmt``, by engine
        (see ``viewers``), each engine's in order: the first is its default.
        Of supports of the former interface, the first of each engine only,
        as before actions: a support given replaces the default one. One
        pass over the actions, as the right-click menu needs all of them."""
        names: dict[str | None, list[str]] = {}
        adapted: set[str | None] = set()
        for action in self.of(fmt, ctx):
            key = engine_key(action)
            if _is_adapted(action):
                if key in adapted:
                    continue
                adapted.add(key)
            names.setdefault(key, []).append(action.name)
        order = [e.key for e in self.engines] + [None]
        return {key: names[key] for key in order if key in names}

    def engine_for(
        self, fmt: DataFormat, ctx: ItemContext, engine: str | None
    ) -> str | None:
        """The engine viewing the item as ``fmt`` when ``engine`` is chosen:
        that engine, if it handles the format; else, for a format it does not
        handle at all (e.g. Markdown for polars), None for the built-in views.
        LookupError if neither can view it: an engine handling the format
        does not leave it to another, even for an item it does not do (the
        user picks one in "Preview as")."""
        viewing = self.of(fmt, ctx)
        if any(engine_key(a) == engine for a in self._registered(fmt, ViewAction)):
            if any(engine_key(a) == engine for a in viewing):
                return engine
        elif any(engine_key(a) is None for a in viewing):
            return None
        raise LookupError(engine)

    def view_names(
        self, fmt: DataFormat, ctx: ItemContext, engine: str | None
    ) -> list[str]:
        """The names of the view actions of ``engine`` (a key; None for the
        built-in views) that do the item as ``fmt``, in order: the first is
        its default (see ``views_by_engine``)."""
        return self.views_by_engine(fmt, ctx).get(engine, [])

    def view(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        limits: ViewLimits,
        engine: str | None,
        action: str | None = None,
    ) -> View:
        """The view of the view action of ``engine`` (a key; None for the
        built-in views) named ``action``, by default the first, installed for
        ``fmt`` that does the item: what it raises is the item's error, no
        other action is tried. RuntimeError if there is none: callers check
        ``viewers`` or ``engine_for`` first. ValueError for an ``action``
        that does not view it, e.g. no longer."""
        actions = [a for a in self.of(fmt, ctx) if engine_key(a) == engine]
        if not actions:
            raise RuntimeError(
                f"no action of {engine or 'the built-in views'} installed views "
                f"{ctx.name} as {fmt.label}; check viewers() first"
            )
        if action is not None:
            actions = [a for a in actions if a.name == action]
            if not actions:
                raise ValueError(f"{ctx.name} cannot be viewed by {action!r}")
        chosen = actions[0]
        return chosen(fmt, ctx, self.options_of(chosen, ctx.location), limits)

    def recipes(self, fmt: DataFormat, ctx: ItemContext) -> list[Recipe]:
        """The recipes of the code actions for ``fmt`` that are installed and
        do the item, as for views: code the kernel could not run is not
        offered. Of supports of the former interface, those of the first
        such support of each engine, so a support given before the defaults
        replaces the default one of its engine. An action that fails gives
        one recipe holding the error, so the others are still shown. Those
        without an engine first, then by engine: those of
        ``engine_preference``, in its order, then the others by key,
        whichever plugin they come from; in the actions' order within one."""
        recipes: list[Recipe] = []
        adapted: set[str] = set()
        for action in self.of(fmt, ctx, CodeAction):
            if _is_adapted(action):
                if action.library in adapted:
                    continue
                adapted.add(action.library)
            recipes += self._recipes_of(action, fmt, ctx)
        order = {key: i for i, key in enumerate(self._engine_preference)}

        def rank(recipe: Recipe) -> tuple[int, int, str]:
            if recipe.engine is None:
                return (0, 0, "")
            return (1, order.get(recipe.engine.key, len(order)), recipe.engine.key)

        return sorted(recipes, key=rank)

    def _recipes_of(
        self, action: Action[Any], fmt: DataFormat, ctx: ItemContext
    ) -> list[Recipe]:
        """The recipes of one code action: one, or one per title for a
        support of the former interface; one holding the error if it fails."""
        common = {"engine": action.engine, "requirements": action.requirements()}
        try:
            codes = action(fmt, ctx, self.options_of(action, ctx.location))
        except Exception as exc:
            title = "" if _is_adapted(action) else action.name
            return [Recipe(title=title, code="", error=error_text(exc), **common)]
        if not _is_adapted(action):
            return [Recipe(title=action.name, code=codes, **common)]
        return [
            Recipe(title=title, code=code, **common) for title, code in codes.items()
        ]


def _is_adapted(action: Action[Any]) -> bool:
    """Whether ``action`` is a support of the former interface."""
    return isinstance(action, (_AdaptedView, _AdaptedCode))


def _check_options(
    engine_options: Mapping[str, Any],
    libraries: Mapping[str, Sequence[Action[Any]]],
    format_names: Sequence[str],
) -> None:
    """ValueError for ``engine_options`` that no action takes (see
    ``ActionChain``); functions are checked when called."""
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
    actions: Sequence[Action[Any]],
    format_names: Sequence[str],
) -> None:
    """ValueError for options of a library for format ``name`` (or all) that
    none of its ``actions`` for it takes: the options of a format and an
    engine are those of all their actions' classes."""
    if name != ALL_FORMATS and name not in format_names:
        raise ValueError(
            f"{where}: unknown format; choose from {[ALL_FORMATS, *format_names]}"
        )
    if callable(values):
        return  # checked when called, by ActionChain.options_of
    if not isinstance(values, dict):
        raise ValueError(f"{where} must be a dict of options")
    taken: set[str] = set()
    for action in actions:
        if name in (ALL_FORMATS, action.format.name):
            taken |= action.options_model.option_names()
    unknown = values.keys() - taken
    if unknown:
        raise ValueError(
            f"{where}: unknown options {sorted(unknown)}; choose from {sorted(taken)}"
        )


def _check_format_names(formats: Sequence[DataFormat]) -> None:
    """ValueError for two format classes of one name: a name is what
    ``engine_options``, previews and the menus choose a format by."""
    classes: dict[str, type[DataFormat]] = {}
    for fmt in formats:
        cls = type(fmt)
        known = classes.setdefault(fmt.name, cls)
        if known is not cls:
            raise ValueError(
                f"format {fmt.name!r} is defined twice: by "
                f"{known.__module__}.{known.__qualname__} and "
                f"{cls.__module__}.{cls.__qualname__}; rename one"
            )


def _check_engine_keys(actions: Sequence[Action[Any]]) -> None:
    """ValueError for two engine classes of one key: actions of an engine
    share its class, so that the explorer offers it once, with one label."""
    engines: dict[str, type[Engine]] = {}
    for action in actions:
        engine = action.engine
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
    actions: Sequence[Action[Any]], preference: Sequence[str]
) -> list[type[Engine]]:
    """The engines of ``actions`` users choose from: installed, viewing
    something (a view action of theirs installed), ``preference``'s first,
    in its order, then the others by key."""
    engines: dict[str, type[Engine]] = {}
    for action in actions:
        engine = action.engine
        if (
            engine is not None
            and isinstance(action, ViewAction)
            and action.is_installed()
        ):
            engines.setdefault(engine.key, engine)
    first = [engines[k] for k in dict.fromkeys(preference) if k in engines]
    rest = sorted((e for e in engines.values() if e not in first), key=lambda e: e.key)
    return first + rest
