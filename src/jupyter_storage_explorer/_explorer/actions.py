"""The explorer's actions (``ActionChain``): the formats they handle, which
action does what to an item, with which engine and options
(``engine_options``), the engines users choose from, and the "Python code"
recipes the code actions give (``Recipe``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._errors import error_text
from jupyter_storage_explorer.actions import Action, CodeAction, ViewAction
from jupyter_storage_explorer.actions.base import check_actions
from jupyter_storage_explorer.actions.python import PythonEngine

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from jupyter_storage_explorer.actions import ActionOptions
    from jupyter_storage_explorer.base import ItemContext, Location
    from jupyter_storage_explorer.engine import Engine, EngineOptions
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.packages import PythonPackage
    from jupyter_storage_explorer.views import View, ViewLimits

# In engine_options, the options of an engine for all formats.
ALL_FORMATS = "*"

# The engines offered first when the explorer is given no engine_preference:
# polars queries the data itself, lazily; pandas reads it whole, so only its
# first rows. Others (e.g. PySpark) follow by key.
DEFAULT_ENGINE_PREFERENCE = ("polars", "pandas")


def engine_key(action: Action[Any]) -> str | None:
    """The key of an action's engine; None for ``PythonEngine``, the built-in
    views', which explorers offer as no engine."""
    return None if action.engine is PythonEngine else action.engine.key


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


class ActionChain:
    """The actions of an explorer, in order, and what is done with them: for
    an item, the actions of its format that are installed and whose check
    agrees, of the engine asked for, with their options. The first such
    view is the item's default.

    Each action gets an ``options_model`` made from ``engine_options``, by
    engine key ("python" for ``PythonEngine``: the built-in views and
    code), then format name, or ``"*"`` for all formats, e.g.
    ``{"polars": {"*": {"storage_options": {...}}, "delta": {"use_pyarrow":
    True}}}``: those of its engine for all formats, then for its format
    (``format.name``), each only if its model has the field. Instead of a
    dict, an entry may be a function of the item's ``Location`` returning
    one, for options depending on where the data is (e.g. an Azure account's
    credentials, by ``location.account_name``): it is called for each view
    and recipe, so keep it quick.

    ``formats`` are the formats files are detected as: one of each
    ``format`` of the actions, in their order (on a tie in priority, the
    first wins: the plugins' actions come first in an explorer), then of the
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
    actions that cannot be used together (``actions.base.check_actions``).
    A function's options are checked when it is called. TypeError for an
    item that is no action.
    """

    def __init__(
        self,
        actions: Iterable[Action[Any]],
        engine_options: EngineOptions | None = None,
        *,
        formats: Iterable[type[DataFormat]] = (),
        engine_preference: Sequence[str] | None = None,
    ) -> None:
        self.actions: list[Action[Any]] = list(actions)
        for action in self.actions:
            if not isinstance(action, Action):
                raise TypeError(
                    f"not an action: {action!r}; decorate it with @view or @code"
                )
        self.engine_options = engine_options or {}
        # What takes options, by engine key ("python" for PythonEngine): what
        # options are checked against.
        self._by_engine: dict[str, list[Action[Any]]] = {}
        for action in self.actions:
            self._by_engine.setdefault(action.engine.key, []).append(action)
        engine_keys = {key for a in self.actions if (key := engine_key(a)) is not None}
        # One object of each format: formats keep what detection finds (e.g.
        # a Parquet dataset's layout) for their actions.
        self.formats: list[DataFormat] = [
            cls()
            for cls in dict.fromkeys([*(a.format for a in self.actions), *formats])
        ]
        self._format_names = [f.name for f in self.formats]
        _check_format_names(self.formats)
        check_actions(self.actions)
        _check_options(self.engine_options, self._by_engine, self._format_names)
        if engine_preference is None:
            engine_preference = DEFAULT_ENGINE_PREFERENCE
        else:
            unknown = [k for k in engine_preference if k not in engine_keys]
            if unknown:
                raise ValueError(
                    f"engine_preference: unknown engines {unknown}; "
                    f"choose from {sorted(engine_keys)}"
                )
        _check_engine_keys(self.actions)
        self.engines = _ordered_engines(self.actions, engine_preference)
        self._engine_preference = list(engine_preference)

    def engine_keys(self) -> set[str]:
        """The keys of the actions' engines, "python" for the built-in ones
        (``PythonEngine``)."""
        return set(self._by_engine)

    def options_of(self, action: Action[Any], location: Location) -> ActionOptions:
        """The options of ``action`` for the item at ``location``: those of
        its engine for all formats, then for its format, those its model
        has (see the class docstring). ValueError for options a function
        returned that no action of the engine takes."""
        key = action.engine.key
        by_format = self.engine_options.get(key, {})
        merged: dict[str, Any] = {}
        for name in (ALL_FORMATS, action.format.name):
            values = by_format.get(name)
            if callable(values):
                values = values(location)
                _check_engine_options(
                    f"engine_options[{key!r}][{name!r}]({location.url!r})",
                    name,
                    values,
                    self._by_engine[key],
                    self._format_names,
                )
            merged.update(values or {})
        taken = action.options_model.option_names()
        return action.options_model(**{k: v for k, v in merged.items() if k in taken})

    def _registered(
        self, fmt: DataFormat, kind: type[Action[Any]]
    ) -> list[Action[Any]]:
        """The actions of ``kind`` for ``fmt``, installed or not, whatever the
        item, in order: those of the most specific of its classes that has
        any. A format's own actions replace its base classes', e.g. a CSV
        file is not viewed as Text, but as CSV or not at all; a format
        without actions of its own has its base classes', e.g. a Python
        script, Text's. The explorer offers the others under the base
        format, e.g. "Preview as" Text (``_detection``)."""
        found = [
            a for a in self.actions if isinstance(fmt, a.format) and isinstance(a, kind)
        ]
        if not found:
            return []
        own = min((a.format for a in found), key=type(fmt).__mro__.index)
        return [a for a in found if a.format is own]

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
    ) -> dict[str | None, list[ViewAction]]:
        """The view actions doing the item as ``fmt``, by engine (see
        ``viewers``), each engine's in order: the first is its default. One
        pass over the actions, as the right-click menu needs all of them."""
        views: dict[str | None, list[ViewAction]] = {}
        for action in self.of(fmt, ctx):
            assert isinstance(action, ViewAction)
            views.setdefault(engine_key(action), []).append(action)
        order = [e.key for e in self.engines] + [None]
        return {key: views[key] for key in order if key in views}

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

    def view(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        limits: ViewLimits,
        engine: str | None,
        action: int | None = None,
    ) -> View:
        """The view of the view action of ``engine`` (a key; None for the
        built-in views) of id ``action``, by default the first, installed for
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
            actions = [a for a in actions if a.id == action]
            if not actions:
                raise ValueError(f"{ctx.name} cannot be viewed by action {action}")
        chosen = actions[0]
        return chosen(fmt, ctx, self.options_of(chosen, ctx.location), limits)

    def recipes(self, fmt: DataFormat, ctx: ItemContext) -> list[Recipe]:
        """The recipes of the code actions for ``fmt`` that are installed and
        do the item, as for views: code the kernel could not run is not
        offered. An action that fails gives a recipe holding the error, so
        the others are still shown. Those of ``PythonEngine`` first, then by
        engine: those of ``engine_preference``, in its order, then the
        others by key, whichever plugin they come from; in the actions' order
        within one."""
        recipes = [
            self._recipe_of(action, fmt, ctx)
            for action in self.of(fmt, ctx, CodeAction)
        ]
        order = {key: i for i, key in enumerate(self._engine_preference)}

        def rank(recipe: Recipe) -> tuple[int, int, str]:
            if recipe.engine is None:
                return (0, 0, "")
            return (1, order.get(recipe.engine.key, len(order)), recipe.engine.key)

        return sorted(recipes, key=rank)

    def _recipe_of(
        self, action: Action[Any], fmt: DataFormat, ctx: ItemContext
    ) -> Recipe:
        """The recipe of one code action, holding the error if it fails."""
        common = {
            "title": action.label,
            "engine": action.engine if engine_key(action) else None,
            "requirements": action.requirements(),
        }
        try:
            code = action(fmt, ctx, self.options_of(action, ctx.location))
        except Exception as exc:
            return Recipe(code="", error=error_text(exc), **common)
        return Recipe(code=code, **common)


def _check_options(
    engine_options: Mapping[str, Any],
    by_engine: Mapping[str, Sequence[Action[Any]]],
    format_names: Sequence[str],
) -> None:
    """ValueError for ``engine_options`` that no action takes (see
    ``ActionChain``); functions are checked when called."""
    for key, by_format in engine_options.items():
        if key not in by_engine:
            raise ValueError(
                f"engine_options: unknown engine {key!r}; "
                f"choose from {sorted(by_engine)}"
            )
        if not isinstance(by_format, dict):
            raise ValueError(
                f"engine_options[{key!r}] must be a dict of format names "
                f"(or {ALL_FORMATS!r}) to options"
            )
        for name, values in by_format.items():
            _check_engine_options(
                f"engine_options[{key!r}][{name!r}]",
                name,
                values,
                by_engine[key],
                format_names,
            )


def _check_engine_options(
    where: str,
    name: str,
    values: Any,
    actions: Sequence[Action[Any]],
    format_names: Sequence[str],
) -> None:
    """ValueError for options of an engine for format ``name`` (or all) that
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
        key = engine_key(action)
        if key is not None and isinstance(action, ViewAction) and action.is_installed():
            engines.setdefault(key, action.engine)
    first = [engines[k] for k in dict.fromkeys(preference) if k in engines]
    rest = sorted((e for e in engines.values() if e not in first), key=lambda e: e.key)
    return first + rest
