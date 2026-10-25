"""Actions: what explorers do with an item of a format, with an engine.

An action is a function decorated with ``view`` (a view of the item, shown
in the preview panel or a tab) or ``code`` (Python loading the item, shown
in "Python code"). A format and an engine may have any number of actions:
e.g. Parquet with Polars viewed in the data browser and in another widget.
Plugins give theirs as ``register_actions(...)``, in order; explorers try
them in that order, and the first matching an item is its default.

Users import these from this module, not from ``formats``: there,
``formats.view`` is a module, which a function of that name would hide.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from jupyter_storage_explorer.formats.base import DataFormat
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.support import (
    IS_SECRET,
    SECRET_KEYS,
    SupportOptions,
)

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View

__all__ = ["Action", "CodeAction", "ViewAction", "code", "register_actions", "view"]

# A check: whether an action does an item (see ``view``).
Check = Callable[[DataFormat, "ItemContext", SupportOptions], bool]

F = TypeVar("F", bound=Callable[..., Any])

# The parameters of each kind of function, in order: checked by name count
# only, as the names are the author's.
_VIEW_PARAMETERS = ("fmt", "ctx", "options", "limits")
_CODE_PARAMETERS = ("fmt", "ctx", "options")


@dataclass(frozen=True, eq=False)
class Action(Generic[F]):
    """An action: a function with what explorers need to know of it, made
    by ``view`` or ``code``. Calling it calls the function.

    Attributes
    ----------
    function : callable
        The function decorated.
    format : type of DataFormat
        The format it handles; its subclasses too.
    engine : type of Engine
        The library it uses, ``PythonEngine`` for Python alone. With
        ``format``, the pair whose options it gets:
        ``engine_options[engine.key][format.name]``.
    name : str
        What the menu shows, ``{format}`` replaced by the format's label.
    requires : tuple of PythonPackage
        Packages it needs besides its engine's.
    check : callable or None
        Whether it does an item (see ``view``); None for every item.
    options_model : type of SupportOptions
        The class of its options, from the annotation of the function's
        ``options`` parameter.
    """

    function: F
    format: type[DataFormat]
    engine: type[Engine]
    name: str
    requires: tuple[PythonPackage, ...]
    check: Check | None
    options_model: type[SupportOptions]

    def __post_init__(self) -> None:
        # Its function's name, docstring and signature, as functools.wraps
        # gives them (inspect.signature follows __wrapped__): an action reads
        # as its function in help(), IDEs and errors. Frozen: set directly.
        for name in functools.WRAPPER_ASSIGNMENTS:
            with contextlib.suppress(AttributeError):
                object.__setattr__(self, name, getattr(self.function, name))
        object.__setattr__(self, "__wrapped__", self.function)

    def __call__(self, *args: Any) -> Any:
        return self.function(*args)

    def requirements(self) -> tuple[PythonPackage, ...]:
        """All the packages it needs: its engine's, then ``requires``."""
        return (*self.engine.requirements, *self.requires)

    def is_installed(self) -> bool:
        """Whether its engine and ``requires`` are installed."""
        return all(p.is_installed() for p in self.requirements())

    def does(self, fmt: DataFormat, ctx: ItemContext, options: SupportOptions) -> bool:
        """Whether it does the item: of its format, and its check agrees."""
        return isinstance(fmt, self.format) and (
            self.check is None or bool(self.check(fmt, ctx, options))
        )


@dataclass(frozen=True, eq=False)
class CodeAction(Action[Callable[..., str]]):
    """An action made by ``code``."""


@dataclass(frozen=True, eq=False)
class ViewAction(Action[Callable[..., "View"]]):
    """An action made by ``view``.

    Attributes
    ----------
    code : CodeAction or None
        The code reproducing what it shows, if any.
    """

    code: CodeAction | None = None


def view(
    *,
    format: type[DataFormat],
    engine: type[Engine],
    name: str = "View {format}",
    requires: tuple[PythonPackage, ...] = (),
    check: Check | None = None,
    code: CodeAction | None = None,
) -> Callable[[Callable[..., View]], ViewAction]:
    """Make a function an action viewing items of a format with an engine.

    The function is called as ``function(fmt, ctx, options, limits)`` and
    returns a ``View``: a ``QueryView`` opens the data in the data browser,
    other views show what the function read. Explorers call it in a worker
    thread, so that a slow read leaves the kernel free; it never touches
    widgets or displays anything. What it raises is the item's error: no
    other action is tried.

    Rules for the function:

    - Its parameters are positional, in this order, under any names:

      - ``fmt``, the format detected, an instance of ``format``;
      - ``ctx``, the item as an ``ItemContext``;
      - ``options``, its options, an instance of the class its annotation
        names (``SupportOptions``, with no fields, without one);
      - ``limits``, how much to read and show, a ``ViewLimits``.
    - Import ``options``' class at run time, not only for type checkers:
      the class is read from the annotation when the function is decorated.
      The annotation resolves in the function's module: define the class at
      its top level, not inside another function.
    - Import the libraries inside the function, e.g. ``import polars as pl``,
      never at the top of the module: plugins load without them.
    - Before reading much, e.g. a whole large file, ask the user first: return
      a ``ViewWithConfirmation``, ``ViewWithChoice`` or ``ViewWithInput``.
    - A view holding something to release, e.g. a connection, releases it in
      a function given to its ``on_close()``.

    Parameters
    ----------
    format : type of DataFormat
        The format viewed, e.g. ``Parquet``; its subclasses too.
    engine : type of Engine
        The library used, e.g. polars-support's ``PolarsEngine``;
        ``PythonEngine`` for Python alone.
    name : str, default "View {format}"
        What the menu shows, ``{format}`` replaced by the format's label.
        It never names the library: the menu shows the engine already.
    requires : tuple of PythonPackage, default ()
        Packages needed besides the engine's, as instances. The action is
        offered only when they are installed.
    check : callable, optional
        ``check(fmt, ctx, options) -> bool``: whether the action does an
        item, e.g. not an image format the library cannot read. It runs on
        the kernel's main thread for each item clicked: it decides from the
        format, the location, the path, the info and the options, never by
        reading the storage. By default, every item of ``format``.
    code : CodeAction, optional
        The code reproducing what the view shows, offered with it. Of the
        same format and engine, and taking the view's options class or one
        of its bases.

    Returns
    -------
    callable
        The decorator, returning a ``ViewAction``.

    Raises
    ------
    TypeError
        When decorating: for arguments of the wrong type, a function of
        another number of parameters, an options annotation that does not
        resolve to a ``SupportOptions`` subclass, or a ``code`` of another
        pair or options class.

    Examples
    --------
    >>> @view(format=Parquet, engine=PolarsEngine)
    ... def parquet_by_polars(fmt, ctx, options: ParquetByPolarsOptions, limits):
    ...     import polars as pl
    ...
    ...     return QueryView(pl.scan_parquet(ctx.url_or_local_path, **options.arguments()))
    """

    def decorate(function: Callable[..., View]) -> ViewAction:
        fields = _fields(
            function,
            _VIEW_PARAMETERS,
            format=format,
            engine=engine,
            name=name,
            requires=requires,
            check=check,
        )
        action = ViewAction(**fields, code=code)
        if code is not None:
            _check_code(action, code)
        return action

    return decorate


def code(
    *,
    format: type[DataFormat],
    engine: type[Engine],
    name: str,
    requires: tuple[PythonPackage, ...] = (),
    check: Check | None = None,
) -> Callable[[Callable[..., str]], CodeAction]:
    """Make a function an action giving code that loads items of a format
    with an engine.

    The function is called as ``function(fmt, ctx, options)`` and returns
    one snippet of Python, shown in "Python code" under its engine. Explorers
    call it in a worker thread. What it raises is shown in place of its
    code; the other snippets are still shown.

    The code runs as it is in a new notebook: its imports first, and what
    else it needs, e.g. a Spark session. Installing the packages and
    configuring access to the storage are left to the user. It reads the
    location (``ctx.url_or_local_path``). The function reads the item only for
    what the code needs to know, e.g. a CSV file's separator. Options go into
    the code only through ``SupportOptions.code_value`` and
    ``code_arguments``, which leave secrets out.

    The function's parameters, the import rules and ``check`` are as for
    ``view``'s, without ``limits``.

    Parameters
    ----------
    format : type of DataFormat
        The format loaded; its subclasses too.
    engine : type of Engine
        The library used; ``PythonEngine`` for Python alone.
    name : str
        What the code does, shown as its title, e.g. "Load as LazyFrame".
        ``{format}`` is replaced by the format's label. It never names the
        library.
    requires : tuple of PythonPackage, default ()
        Packages needed besides the engine's.
    check : callable, optional
        As ``view``'s.

    Returns
    -------
    callable
        The decorator, returning a ``CodeAction``.

    Raises
    ------
    TypeError
        When decorating, as ``view``.

    Examples
    --------
    >>> @code(format=Parquet, engine=PolarsEngine, name="Load as LazyFrame")
    ... def parquet_as_lazy_frame(fmt, ctx, options: ParquetByPolarsOptions):
    ...     kwargs = format_arguments(options.code_arguments())
    ...     return f"import polars as pl\\n\\ndf = pl.scan_parquet({ctx.url_or_local_path!r}{kwargs})"
    """

    def decorate(function: Callable[..., str]) -> CodeAction:
        fields = _fields(
            function,
            _CODE_PARAMETERS,
            format=format,
            engine=engine,
            name=name,
            requires=requires,
            check=check,
        )
        return CodeAction(**fields)

    return decorate


def register_actions(*actions: Action[Any]) -> tuple[Action[Any], ...]:
    """The actions of a plugin, in order, checked together.

    The order is the one explorers try them in: the first action matching an
    item is its default, e.g. what a double-click previews.

    Parameters
    ----------
    *actions : Action
        Functions decorated with ``view`` or ``code``.

    Returns
    -------
    tuple of Action
        ``actions``, for the plugin's ``actions`` property.

    Raises
    ------
    TypeError
        For an argument that is no action.
    ValueError
        For two actions of one kind, format and engine with one name, a
        view's ``code`` missing from ``actions``, or options classes of one
        format and engine whose fields of one name differ in type or in
        what is secret.

    Examples
    --------
    >>> class PolarsSupport(StorageExplorerPlugin):
    ...     key = "polars-support"
    ...
    ...     @property
    ...     def actions(self):
    ...         return register_actions(parquet_by_polars, parquet_as_lazy_frame)
    """
    for action in actions:
        if not isinstance(action, Action):
            raise TypeError(
                f"not an action: {action!r}; decorate it with @view or @code"
            )
    check_actions(actions)
    listed = set(actions)
    for action in actions:
        if isinstance(action, ViewAction) and action.code not in (None, *listed):
            raise ValueError(
                f"{_named(action)}: its code {_named(action.code)} is not "
                "registered with it"
            )
    return tuple(actions)


def check_actions(actions: tuple[Action[Any], ...] | list[Action[Any]]) -> None:
    """ValueError for actions that cannot be used together: two of one kind,
    format and engine with one name, or options classes of one format and
    engine whose fields of one name differ (see ``register_actions``).
    Explorers check all their actions so, whatever they come from."""
    names: dict[tuple[type, type[DataFormat], str, str], Action[Any]] = {}
    for action in actions:
        key = (type(action), action.format, action.engine.key, action.name)
        known = names.setdefault(key, action)
        if known is not action:
            raise ValueError(
                f"two actions named {action.name!r} for {action.format.label} "
                f"with {action.engine.key}: {_where(known)} and {_where(action)}; "
                "rename one"
            )
    fields: dict[tuple[type[DataFormat], str, str], tuple[Any, Action[Any]]] = {}
    for action in actions:
        for name, shape in _field_shapes(action.options_model).items():
            key = (action.format, action.engine.key, name)
            known_shape, known = fields.setdefault(key, (shape, action))
            if known_shape != shape:
                raise ValueError(
                    f"option {name!r} of {action.format.label} with "
                    f"{action.engine.key} differs between "
                    f"{known.options_model.__qualname__} ({_where(known)}) and "
                    f"{action.options_model.__qualname__} ({_where(action)}): "
                    "one type, and secret in both or neither"
                )


def _fields(
    function: Callable[..., Any],
    parameters: tuple[str, ...],
    *,
    format: type[DataFormat],
    engine: type[Engine],
    name: str,
    requires: tuple[PythonPackage, ...],
    check: Check | None,
) -> dict[str, Any]:
    """An action's fields, checked (see ``view``'s Raises)."""
    where = getattr(function, "__qualname__", repr(function))
    if not (isinstance(format, type) and issubclass(format, DataFormat)):
        raise TypeError(f"{where}: format must be a DataFormat class, not {format!r}")
    if not (isinstance(engine, type) and issubclass(engine, Engine)):
        raise TypeError(
            f"{where}: engine must be an Engine class, e.g. PythonEngine, "
            f"not {engine!r}"
        )
    if not isinstance(requires, tuple) or not all(
        isinstance(p, PythonPackage) for p in requires
    ):
        raise TypeError(f"{where}: requires must be a tuple of PythonPackage instances")
    if check is not None and not callable(check):
        raise TypeError(f"{where}: check must be callable, not {check!r}")
    if not callable(function):
        raise TypeError(f"{where}: not a function")
    try:
        label = name.format(format=format.label)
    except (KeyError, IndexError, ValueError) as exc:
        raise TypeError(f"{where}: name may hold only {{format}}: {name!r}") from exc
    every = list(inspect.signature(function).parameters.values())
    positional = [
        p for p in every if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    # Keyword-only parameters with defaults are harmless: never passed.
    others = [
        p
        for p in every
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        or (p.kind == p.KEYWORD_ONLY and p.default is p.empty)
    ]
    if len(positional) != len(parameters) or others:
        raise TypeError(
            f"{where}: takes {len(parameters)} positional parameters "
            f"({', '.join(parameters)}), and no others"
        )
    return {
        "function": function,
        "format": format,
        "engine": engine,
        "name": label,
        "requires": requires,
        "check": check,
        "options_model": _options_model(function, positional[2].name, format, where),
    }


def _options_model(
    function: Callable[..., Any], parameter: str, format: type[DataFormat], where: str
) -> type[SupportOptions]:
    """The class ``function``'s ``parameter`` is annotated with, resolved in
    the function's module; ``SupportOptions`` without an annotation."""
    annotation = inspect.get_annotations(function).get(parameter)
    if annotation is None:
        return SupportOptions
    if isinstance(annotation, str):
        try:
            annotation = eval(annotation, getattr(function, "__globals__", {}))
        except Exception as exc:
            raise TypeError(
                f"{where}: the annotation of {parameter!r}, {annotation!r}, does not "
                "resolve: import its class at run time, not under TYPE_CHECKING"
            ) from exc
    if not (isinstance(annotation, type) and issubclass(annotation, SupportOptions)):
        raise TypeError(
            f"{where}: {parameter!r} must be annotated with a SupportOptions "
            f"subclass, not {annotation!r}"
        )
    return annotation


def _check_code(action: ViewAction, code: CodeAction) -> None:
    """TypeError for a view's ``code`` that cannot reproduce it: not a code
    action, of another format or engine, or taking options the view's class
    does not have."""
    where = _named(action)
    if not isinstance(code, CodeAction):
        raise TypeError(f"{where}: code must be a function decorated with @code")
    if (code.format, code.engine) != (action.format, action.engine):
        raise TypeError(
            f"{where}: its code {_named(code)} is of another format or engine"
        )
    if not issubclass(action.options_model, code.options_model):
        raise TypeError(
            f"{where}: its code takes {code.options_model.__qualname__}, which is "
            f"neither {action.options_model.__qualname__} nor one of its bases"
        )


def _field_shapes(
    model: type[SupportOptions],
) -> dict[str, tuple[Any, bool, tuple[str, ...]]]:
    """``model``'s fields by name: their type and what of them is secret,
    for comparing classes. Types are resolved where the class's module
    allows it, so that two spellings of one type compare equal; else
    compared as written."""
    try:
        types: dict[str, Any] = typing.get_type_hints(model)
    except Exception:  # e.g. a name imported only for type checkers
        types = {}
    return {
        f.name: (
            types.get(f.name, f.type),
            bool(f.metadata.get(IS_SECRET)),
            tuple(sorted(f.metadata.get(SECRET_KEYS, ()))),
        )
        for f in dataclasses.fields(model)
    }


def _named(action: Action[Any]) -> str:
    return getattr(action.function, "__qualname__", repr(action.function))


def _where(action: Action[Any]) -> str:
    """Where an action is defined, for errors naming two of them."""
    function = action.function
    return f"{getattr(function, '__module__', '?')}.{_named(action)}"
