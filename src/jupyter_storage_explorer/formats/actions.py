"""Actions: what explorers do with an item of a format, with an engine.

An action is a function decorated with ``view`` (a view of the item, shown
in the preview panel or a tab) or ``code`` (Python loading the item, shown
in "Python code"). A format and an engine may have any number of actions:
e.g. Parquet with Polars viewed in the data browser and in another widget.
Plugins give theirs as ``register_actions(...)``, in order; explorers try
them in that order, and the first matching an item is its default. An
action's options are an ``ActionOptions`` subclass; ``util`` has the
helpers of their fields and of generated code.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import inspect
import itertools
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import narwhals as nw

from jupyter_storage_explorer.formats.base import DataFormat
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.packages import PythonPackage
from jupyter_storage_explorer.formats.views import (
    JupyterWidgetView,
    QueryView,
    TextView,
    TreeView,
    View,
    is_jupyter_widget,
)
from jupyter_storage_explorer.util import (
    IS_SECRET,
    LIBRARY_DEFAULT,
    SECRET_KEYS,
    _shown_options,
)

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext

__all__ = [
    "Action",
    "ActionOptions",
    "CodeAction",
    "ViewAction",
    "code",
    "register_actions",
    "view",
]


@dataclass(frozen=True, kw_only=True)
class ActionOptions:
    """The options of an action: none. The base of actions' options.

    An action taking options annotates its ``options`` parameter with a
    subclass: a frozen, keyword-only dataclass whose fields are the options,
    each with a default, as users may set none of them. Explorers make one
    from ``engine_options``, by the action's engine and format, and pass it
    to the action and its check. Subclasses of a library's options share
    them, e.g. its storage options, which ``engine_options``' ``"*"`` then
    sets for all its formats.

    Options are data. What actions do with them is in functions taking them;
    methods only give views of them, e.g. ``code_value``.

    Mark secrets with ``secret_field`` (a whole value) or
    ``secret_dict_field`` (keys of a mapping), and give generated code the
    options through ``code_value``, which leaves them out.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class DuckDBOptions(ActionOptions):
    ...     config: Mapping[str, Any] | None = secret_dict_field(
    ...         default=None, secret_keys=["s3_secret_access_key"]
    ...     )
    >>> @view(format=Parquet, engine=DuckDBEngine)
    ... def parquet_view(fmt, ctx, options: DuckDBOptions, limits):
    ...     import duckdb
    ...
    ...     con = duckdb.connect(config=dict(options.config or {}))
    ...     ...
    >>> StorageExplorer(
    ...     "data",
    ...     actions=[parquet_view],
    ...     engine_options={"duckdb": {"*": {"config": {"threads": 4}}}},
    ... )
    """

    @classmethod
    def option_names(cls) -> frozenset[str]:
        """The options: the names of the fields, those ``engine_options`` may
        set.

        Returns
        -------
        frozenset of str
            E.g. ``{"storage_options", "credential_provider"}`` for
            ``PolarsOptions``.
        """
        return frozenset(f.name for f in dataclasses.fields(cls))

    def code_value(self, name: str) -> Any:
        """Option ``name`` as generated code may show it: None for a secret
        (``secret_field``) or an object that is not plain data; a mapping
        without its secret keys (``secret_dict_field``) and keys that look
        like credentials, None if nothing is left.

        Parameters
        ----------
        name : str
            A field's name.

        Returns
        -------
        Any
            The value to show, or None to leave the option out.
        """
        [field] = [f for f in dataclasses.fields(self) if f.name == name]
        if field.metadata.get(IS_SECRET):
            return None
        secret_keys = field.metadata.get(SECRET_KEYS, ())
        shown = _shown_options({name: getattr(self, name)}, frozenset(secret_keys))
        value = shown.get(name)
        return None if isinstance(value, dict) and not value else value

    def arguments(self) -> dict[str, Any]:
        """The library's arguments the options give: the fields whose default
        is ``LIBRARY_DEFAULT`` (each an argument of its name), those given,
        in the fields' order. Pass them to the library's reader as they are.

        Returns
        -------
        dict
            E.g. ``{"has_header": False}`` for
            ``CsvByPolarsOptions(has_header=False)``.

        Examples
        --------
        >>> @dataclass(frozen=True, kw_only=True)
        ... class CsvByDuckDBOptions(ActionOptions):
        ...     header: bool | LibraryDefault = LIBRARY_DEFAULT
        ...     delim: str | LibraryDefault = LIBRARY_DEFAULT
        >>> CsvByDuckDBOptions(header=True).arguments()
        {'header': True}
        """
        return {
            f.name: value
            for f in dataclasses.fields(self)
            if f.default is LIBRARY_DEFAULT
            and (value := getattr(self, f.name)) is not LIBRARY_DEFAULT
        }

    def code_arguments(self) -> dict[str, Any]:
        """``arguments()`` as generated code may show them (``code_value``):
        without secrets and values that are objects rather than plain data
        (e.g. polars' data types); None, a value given, is kept. For
        ``format_arguments``.

        Returns
        -------
        dict
        """
        shown = {}
        for name, value in self.arguments().items():
            if value is None:
                shown[name] = None
            elif (code := self.code_value(name)) is not None:
                shown[name] = code
        return shown


# A check: whether an action does an item (see ``view``).
Check = Callable[[DataFormat, "ItemContext", ActionOptions], bool]

F = TypeVar("F", bound=Callable[..., Any])

# The actions' ids, in the order they are made (see Action.id).
_ids = itertools.count(1)

# What an action's function may take, by parameter name, from what the
# explorer calls the action with: (fmt, ctx, options, limits). The function
# names those it needs, in any order.
_ARGUMENTS: dict[str, Callable[[Any, Any, Any, Any], Any]] = {
    "fmt": lambda fmt, ctx, options, limits: fmt,
    "ctx": lambda fmt, ctx, options, limits: ctx,
    "options": lambda fmt, ctx, options, limits: options,
    "limits": lambda fmt, ctx, options, limits: limits,
    "url": lambda fmt, ctx, options, limits: ctx.url,
    "url_or_local_path": lambda fmt, ctx, options, limits: ctx.url_or_local_path,
    "path": lambda fmt, ctx, options, limits: ctx.path,
    "name": lambda fmt, ctx, options, limits: ctx.name,
    "size": lambda fmt, ctx, options, limits: ctx.size,
    "is_dir": lambda fmt, ctx, options, limits: ctx.is_dir,
    "fs": lambda fmt, ctx, options, limits: ctx.fs,
}
_VIEW_PARAMETERS = tuple(_ARGUMENTS)
# Code shows nothing: no limits.
_CODE_PARAMETERS = tuple(n for n in _ARGUMENTS if n != "limits")


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
    label : str
        What users see: a view's entry in the menus, a code action's title in
        "Python code". ``{format}`` and ``{engine}`` are replaced by the
        labels of its format and engine.
    requires : tuple of PythonPackage
        Packages it needs besides its engine's.
    check : callable or None
        Whether it does an item (see ``view``); None for every item.
    options_model : type of ActionOptions
        The class of its options, from the annotation of the function's
        ``options`` parameter.
    id : int
        What the page names it by, e.g. the view chosen in "Preview as":
        a number of its own, given when the action is made, the same for the
        kernel's life.
    """

    function: F
    format: type[DataFormat]
    engine: type[Engine]
    label: str
    requires: tuple[PythonPackage, ...]
    check: Check | None
    options_model: type[ActionOptions]
    id: int = dataclasses.field(
        init=False, default_factory=lambda: next(_ids), compare=False
    )

    def __post_init__(self) -> None:
        # Its function's name, docstring and signature, as functools.wraps
        # gives them (inspect.signature follows __wrapped__): an action reads
        # as its function in help(), IDEs and errors. Frozen: set directly.
        for name in functools.WRAPPER_ASSIGNMENTS:
            with contextlib.suppress(AttributeError):
                object.__setattr__(self, name, getattr(self.function, name))
        object.__setattr__(self, "__wrapped__", self.function)
        # The function's parameters it is called with, by name (_ARGUMENTS):
        # read here, so that dataclasses.replace with another function reads
        # that one's.
        object.__setattr__(self, "_parameters", _taken(self.function))

    def __call__(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        options: ActionOptions,
        limits: Any = None,
    ) -> Any:
        """Call the function with the parameters it names (see ``view``)."""
        return self.function(
            **{
                name: _ARGUMENTS[name](fmt, ctx, options, limits)
                for name in self._parameters
            }
        )

    def requirements(self) -> tuple[PythonPackage, ...]:
        """All the packages it needs: its engine's, then ``requires``."""
        return (*self.engine.requirements, *self.requires)

    def is_installed(self) -> bool:
        """Whether its engine and ``requires`` are installed."""
        return all(p.is_installed() for p in self.requirements())

    def does(self, fmt: DataFormat, ctx: ItemContext, options: ActionOptions) -> bool:
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

    def __call__(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        options: ActionOptions,
        limits: Any = None,
    ) -> View:
        """The function's view, plain data made a view (see ``view``)."""
        return _as_view(super().__call__(fmt, ctx, options, limits))


def view(
    *types: type[DataFormat | Engine],
    format: type[DataFormat] | None = None,
    engine: type[Engine] | None = None,
    label: str = "View as {format} ({engine})",
    requires: tuple[PythonPackage, ...] = (),
    check: Check | None = None,
    code: CodeAction | None = None,
) -> Callable[[Callable[..., Any]], ViewAction]:
    """Make a function an action viewing items of a format with an engine.

    The function returns what to show: a ``View``, or plain data, made one.

    - A dataframe, any the data browser reads, best a lazy one, opens in the
      data browser, as a ``QueryView`` of it.
    - A ``str`` is shown as text (``TextView``).
    - A ``dict`` or ``list`` is shown as a tree (``TreeView``).
    - A Jupyter widget, an ``ipywidgets.DOMWidget``, is shown as it is
      (``JupyterWidgetView``).

    Explorers call it in a worker thread, so that a slow read leaves the
    kernel free. It displays nothing, and touches no widget shown: it may
    create the widget it returns, which the view then owns. What it
    raises is the item's error: no other action is tried.

    Rules for the function:

    - It takes the parameters it names, in any order, of these:

      - ``url``, the item's URL, also of a local file, which fsspec opens;
      - ``url_or_local_path``, where most libraries read the item: its URL,
        but a local file's plain path;
      - ``path``, ``name``, ``size``, ``is_dir`` and ``fs``, those of the
        item (see ``ItemContext``);
      - ``ctx``, the item as an ``ItemContext``;
      - ``fmt``, the format detected, an instance of ``format``;
      - ``options``, its options, an instance of the class its annotation
        names (``ActionOptions``, with no fields, without one);
      - ``limits``, how much to read and show, a ``ViewLimits``.

      Others are allowed only with a default, which they keep.
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
    *types : type of DataFormat or Engine
        The format and the engine, in any order, as ``format`` and
        ``engine`` give them: ``@view(Parquet, PolarsEngine)``.
    format : type of DataFormat
        The format viewed, e.g. ``Parquet``; its subclasses too. Required,
        here or in ``types``; ``file_format(...)`` makes one.
    engine : type of Engine, default PythonEngine
        The library used, e.g. polars-support's ``PolarsEngine``;
        ``PythonEngine`` for Python alone.
    label : str, default "View as {format} ({engine})"
        What the menus show for the view when its engine has several views
        of an item, e.g. "Parquet in a widget ({engine})". ``{format}`` and
        ``{engine}`` are replaced by the labels of ``format`` and
        ``engine``. Unique among the views of one format and engine.
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
        When decorating: for arguments of the wrong type, no format, a
        parameter the function cannot be given, an options annotation that
        does not resolve to a ``ActionOptions`` subclass, or a ``code`` of
        another pair or options class.

    Examples
    --------
    >>> @view(Parquet, PolarsEngine, label="First rows ({engine})")
    ... def head(url_or_local_path):
    ...     import polars as pl
    ...
    ...     return pl.scan_parquet(url_or_local_path).head(100)

    >>> @view(format=Parquet, engine=PolarsEngine)
    ... def parquet_by_polars(fmt, ctx, options: ParquetByPolarsOptions, limits):
    ...     import polars as pl
    ...
    ...     return QueryView(pl.scan_parquet(ctx.url_or_local_path, **options.arguments()))
    """
    format, engine = _format_and_engine(types, format, engine)

    def decorate(function: Callable[..., Any]) -> ViewAction:
        fields = _fields(
            function,
            _VIEW_PARAMETERS,
            format=format,
            engine=engine,
            label=label,
            requires=requires,
            check=check,
        )
        action = ViewAction(**fields, code=code)
        if code is not None:
            _check_code(action, code)
        return action

    return decorate


def code(
    *types: type[DataFormat | Engine],
    format: type[DataFormat] | None = None,
    engine: type[Engine] | None = None,
    label: str | None = None,
    requires: tuple[PythonPackage, ...] = (),
    check: Check | None = None,
) -> Callable[[Callable[..., str]], CodeAction]:
    """Make a function an action giving code that loads items of a format
    with an engine.

    The function returns one snippet of Python, shown in "Python code" under
    its engine. Explorers call it in a worker thread. What it raises is
    shown in place of its code; the other snippets are still shown.

    The code runs as it is in a new notebook: its imports first, and what
    else it needs, e.g. a Spark session. Installing the packages and
    configuring access to the storage are left to the user. It reads the
    location (``url`` or ``url_or_local_path``). The function reads the item only for what the code
    needs to know, e.g. a CSV file's separator. Options go into the code
    only through ``ActionOptions.code_value`` and ``code_arguments``, which
    leave secrets out.

    The function's parameters, the import rules and ``check`` are as for
    ``view``'s, without ``limits``.

    Parameters
    ----------
    *types : type of DataFormat or Engine
        The format and the engine, in any order, as ``format`` and
        ``engine`` give them: ``@code(Parquet, PolarsEngine)``.
    format : type of DataFormat
        The format loaded; its subclasses too. Required, here or in
        ``types``.
    engine : type of Engine, default PythonEngine
        The library used; ``PythonEngine`` for Python alone.
    label : str, optional
        What the code does, shown as its title under its engine in "Python
        code", e.g. "Load as LazyFrame". ``{format}`` and ``{engine}`` are
        replaced by the labels of ``format`` and ``engine``. Unique among
        the code actions of one format and engine. By default, the
        function's name, e.g. "Pretty print" for ``pretty_print``.
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
    >>> @code(file_format(extensions=".abc"))
    ... def pretty_print(url):
    ...     return f"import fsspec, json\\n\\nprint(json.dumps(json.loads(fsspec.open({url!r}).open().read()), indent=4))"

    >>> @code(format=Parquet, engine=PolarsEngine, label="Load as LazyFrame")
    ... def parquet_as_lazy_frame(url_or_local_path, options: ParquetByPolarsOptions):
    ...     kwargs = format_arguments(options.code_arguments())
    ...     return f"import polars as pl\\n\\ndf = pl.scan_parquet({url_or_local_path!r}{kwargs})"
    """
    format, engine = _format_and_engine(types, format, engine)

    def decorate(function: Callable[..., str]) -> CodeAction:
        fields = _fields(
            function,
            _CODE_PARAMETERS,
            format=format,
            engine=engine,
            label=label if label is not None else _label_of(function),
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
        For two actions of one kind, format and engine with one label, a
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
    format and engine with one label, which users could not tell apart, or
    options classes of one format and engine whose fields of one name differ
    (see ``register_actions``). Explorers check all their actions so,
    whatever they come from."""
    labels: dict[tuple[type, type[DataFormat], str, str], Action[Any]] = {}
    for action in actions:
        key = (type(action), action.format, action.engine.key, action.label)
        known = labels.setdefault(key, action)
        if known is not action:
            raise ValueError(
                f"two actions labelled {action.label!r} for {action.format.label} "
                f"with {action.engine.key}: {_where(known)} and {_where(action)}; "
                "give one another label"
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
    label: str,
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
    if not isinstance(label, str):
        raise TypeError(f"{where}: label must be a str, not {label!r}")
    try:
        shown = label.format(format=format.label, engine=engine.label)
    except (KeyError, IndexError, ValueError) as exc:
        raise TypeError(
            f"{where}: label may hold only {{format}} and {{engine}}: {label!r}"
        ) from exc
    _check_parameters(function, parameters, where)
    return {
        "function": function,
        "format": format,
        "engine": engine,
        "label": shown,
        "requires": requires,
        "check": check,
        "options_model": _options_model(function, "options", format, where),
    }


def _check_parameters(
    function: Callable[..., Any], parameters: tuple[str, ...], where: str
) -> None:
    """TypeError for a parameter of ``function`` an action cannot give: one
    not of ``parameters`` without a default, positional-only, or ``*args``
    and ``**kwargs``."""
    for p in inspect.signature(function).parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise TypeError(
                f"{where}: {p.name!r}: parameters are given by name: no "
                "positional-only parameters, *args or **kwargs"
            )
        # Others are fine with a default, never given.
        if p.name not in parameters and p.default is p.empty:
            raise TypeError(
                f"{where}: cannot be given {p.name!r}; it may take "
                f"{', '.join(parameters)}"
            )


def _taken(function: Callable[..., Any]) -> tuple[str, ...]:
    """The parameters an action gives ``function``: those it names of
    ``_ARGUMENTS``. Checked when decorating (see ``_fields``)."""
    try:
        names = inspect.signature(function).parameters
    except (TypeError, ValueError):  # e.g. a builtin
        return ()
    return tuple(n for n in names if n in _ARGUMENTS)


def _format_and_engine(
    types: tuple[Any, ...], format: Any, engine: Any
) -> tuple[Any, Any]:
    """The format and engine given to ``view`` or ``code``: positionally, as
    ``types``, or by keyword; PythonEngine without an engine. TypeError for
    one given twice, no format, or something else; ``_fields`` checks the
    keywords' types."""
    for given in types:
        if isinstance(given, type) and issubclass(given, DataFormat):
            if format is not None:
                raise TypeError(f"two formats given: {format!r} and {given!r}")
            format = given
        elif isinstance(given, type) and issubclass(given, Engine):
            if engine is not None:
                raise TypeError(f"two engines given: {engine!r} and {given!r}")
            engine = given
        else:
            raise TypeError(
                f"not a DataFormat or Engine class: {given!r}; give the "
                "others by keyword, e.g. label=..."
            )
    if format is None:
        raise TypeError("no format given: e.g. @view(Parquet) or file_format(...)")
    if engine is None:
        # Here, as formats.python's actions import this module.
        from jupyter_storage_explorer.formats.python import (  # noqa: PLC0415
            PythonEngine,
        )

        engine = PythonEngine
    return format, engine


def _label_of(function: Callable[..., Any]) -> str:
    """A code action's default label: its function's name as words, e.g.
    "Pretty print" for ``pretty_print``."""
    words = getattr(function, "__name__", "code").strip("_").replace("_", " ")
    return words[:1].upper() + words[1:] or "Code"


def _as_view(value: Any) -> View:
    """What a view action's function returned, as a view: a ``View`` as it
    is; a ``str`` as text, a ``dict`` or ``list`` as a tree, a dataframe in
    the data browser, and a Jupyter widget as it is. TypeError for anything
    else."""
    if isinstance(value, View):
        return value
    if isinstance(value, str):
        return TextView(text=value)
    if isinstance(value, (dict, list)):
        return TreeView(value=value)
    if nw.from_native(value, pass_through=True) is not value:
        return QueryView(data=value)
    if is_jupyter_widget(value):
        return JupyterWidgetView(widget=value)
    raise TypeError(
        "a view returns a View, a str, a dict or list, a dataframe, or a "
        f"Jupyter widget, not {type(value).__name__}"
    )


def _options_model(
    function: Callable[..., Any], parameter: str, format: type[DataFormat], where: str
) -> type[ActionOptions]:
    """The class ``function``'s ``parameter`` is annotated with, resolved in
    the function's module; ``ActionOptions`` without an annotation."""
    annotation = inspect.get_annotations(function).get(parameter)
    if annotation is None:
        return ActionOptions
    if isinstance(annotation, str):
        try:
            annotation = eval(annotation, getattr(function, "__globals__", {}))
        except Exception as exc:
            raise TypeError(
                f"{where}: the annotation of {parameter!r}, {annotation!r}, does not "
                "resolve: import its class at run time, not under TYPE_CHECKING"
            ) from exc
    if not (isinstance(annotation, type) and issubclass(annotation, ActionOptions)):
        raise TypeError(
            f"{where}: {parameter!r} must be annotated with a ActionOptions "
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
    model: type[ActionOptions],
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
