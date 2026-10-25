"""How to handle data in a format with a library: the ``FormatSupport``
interface, with ``SupportOptions``, the base of its options, and the helpers
of the code supports generate (``format_kwargs``, ``format_arguments``, the
secret fields), and ``LIBRARY_DEFAULT``, the default of options that are a
library's arguments. The core's supports are in supports/python.py, the
engines' in their plugins; explorers choose and call them with their own
chain (``_explorer/supports.py``)."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

# At run time, not only for type checkers: EngineOptions, a public alias,
# names it.
from jupyter_storage_explorer.location import Location

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
    from jupyter_storage_explorer.formats.engine import Engine
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.view import View, ViewLimits

# What a support can be asked to do with an item, each the name of the method
# doing it: view it (the preview panel, a tab), give recipes, the code
# loading it ("Python code"). FormatSupport.supports tells whether it does.
Task: TypeAlias = Literal["view", "recipe"]
TASKS: tuple[Task, ...] = ("view", "recipe")

# StorageExplorer's engine_options: {engine key: {format name or "*": options}},
# the options a dict, or a function of the item's location returning one
# (see StorageExplorer's engine_options).
EngineOptions: TypeAlias = Mapping[
    str, Mapping[str, Mapping[str, Any] | Callable[[Location], Mapping[str, Any]]]
]
# The former name of EngineOptions, kept as an alias. To be removed in the
# major release.
FormatOptions: TypeAlias = EngineOptions


def format_kwargs(**kwargs: Any) -> str:
    """Python source for keyword arguments following others in a call, each
    after ", "; those that are None are left out, so it may be empty. For the
    ``{kwargs}`` of recipe templates, e.g. ``"df = pl.read_csv({url}{kwargs})"``,
    with options as ``SupportOptions.code_value`` gives them.

    >>> format_kwargs(sep=";", storage_options=None)
    ", sep=';'"
    """
    return "".join(f", {k}={v!r}" for k, v in kwargs.items() if v is not None)


# Option names that look like credentials are left out of generated code,
# since code gets copied, shared and saved in notebooks: a safety net under
# the secrets options declare (secret_field, secret_dict_field).
_SECRET_OPTION = re.compile(
    r"key|secret|token|password|passwd|credential|sas|connection_string", re.IGNORECASE
)


def _is_plain(value: Any) -> bool:
    """Whether ``repr(value)`` is valid Python, so it can appear in generated code."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_plain(v) for v in value)
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _is_plain(v) for k, v in value.items())
    return False


def _shown_options(
    options: Mapping[str, Any] | None, secret_keys: frozenset[str]
) -> dict[str, Any]:
    """``options`` fit to put in generated code; empty for None: without
    ``secret_keys`` (at any depth), names that look like credentials anyway,
    and values that are objects rather than plain data (e.g. the filesystem
    a DirFileSystem wraps)."""
    out: dict[str, Any] = {}
    for key, value in (options or {}).items():
        if key in secret_keys or _SECRET_OPTION.search(key):
            continue
        if isinstance(value, Mapping):
            # Filtered key by key, keeping e.g. client_kwargs' endpoint_url.
            out[key] = _shown_options(value, secret_keys)
        elif _is_plain(value):
            out[key] = value
    return out


# Field metadata of options: the whole value is a secret (``secret_field``),
# or these keys of a mapping are (``secret_dict_field``).
IS_SECRET = "is_secret"
SECRET_KEYS = "secret_keys"


def secret_field(**kwargs: Any) -> Any:
    """A field of options whose value is a secret, e.g. a password or a
    credential object: ``dataclasses.field(**kwargs)``, marked so, and left
    out of the options' ``repr``.

    Generated code never shows it (``SupportOptions.code_value`` gives None).

    Parameters
    ----------
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(SupportOptions):
    ...     password: str | None = secret_field(default=None)
    """
    metadata = {**kwargs.pop("metadata", {}), IS_SECRET: True}
    kwargs.setdefault("repr", False)
    return dataclasses.field(**kwargs, metadata=metadata)


def secret_dict_field(*, secret_keys: Iterable[str], **kwargs: Any) -> Any:
    """A field of options holding a mapping some of whose keys are secrets,
    e.g. storage options with an account key: ``dataclasses.field(**kwargs)``,
    naming them.

    Generated code shows the mapping without them, at any depth
    (``SupportOptions.code_value``), nor keys that look like credentials
    anyway.

    Parameters
    ----------
    secret_keys : iterable of str
        The keys whose values are secrets, e.g. ``["connection_string",
        "shared_key"]``.
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(SupportOptions):
    ...     storage_options: Mapping[str, Any] | None = secret_dict_field(
    ...         default=None, secret_keys=["connection_string", "shared_key"]
    ...     )
    """
    metadata = {**kwargs.pop("metadata", {}), SECRET_KEYS: tuple(secret_keys)}
    return dataclasses.field(**kwargs, metadata=metadata)


class LibraryDefault:
    """The type of ``LIBRARY_DEFAULT``, the default of options that are a
    library's arguments: one object, never equal to a value given."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "LIBRARY_DEFAULT"

    def __reduce__(self) -> str:
        # Pickled (e.g. copied) as the module's object itself.
        return "LIBRARY_DEFAULT"


LIBRARY_DEFAULT = LibraryDefault()
"""The default of an option that is one of the library's arguments: not
passed, so the library's own default applies (``SupportOptions.arguments``).
Not None, which some arguments take as a value (e.g. polars'
``quote_char=None``: no quoting)."""


def format_arguments(arguments: Mapping[str, Any]) -> str:
    """Python source for keyword arguments following others in a call, each
    after ", ", None included: for ``SupportOptions.code_arguments``.

    >>> format_arguments({"has_header": False, "quote_char": None})
    ", has_header=False, quote_char=None"
    """
    return "".join(f", {k}={v!r}" for k, v in arguments.items())


@dataclass(frozen=True, kw_only=True)
class SupportOptions:
    """The options of a support: none. The base of supports' options.

    A support taking options names a subclass as its ``options_model``: a
    frozen, keyword-only dataclass whose fields are the options, each with a
    default, as users may set none of them. Explorers make one from
    ``engine_options`` and pass it to each of the support's methods.
    Subclasses of a library's options share them, e.g. its storage options,
    which ``engine_options``' ``"*"`` then sets for all its formats.

    Mark secrets with ``secret_field`` (a whole value) or
    ``secret_dict_field`` (keys of a mapping), and give generated code the
    options through ``code_value``, which leaves them out.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class DuckDBOptions(SupportOptions):
    ...     config: Mapping[str, Any] | None = secret_dict_field(
    ...         default=None, secret_keys=["s3_secret_access_key"]
    ...     )
    >>> class ParquetByDuckDB(FormatSupport):
    ...     options_model = DuckDBOptions
    ...     def view(self, fmt, ctx, options, limits):
    ...         con = DuckDB().load().connect(config=dict(options.config or {}))
    ...         ...
    >>> StorageExplorer(
    ...     "data",
    ...     supports=[ParquetByDuckDB],
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
        ... class CsvByDuckDBOptions(SupportOptions):
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


class FormatSupport:
    """How to view or load the data of one format with one library.

    Subclass it to handle a format with a library of your own, e.g. Parquet
    with DuckDB, and give it to ``StorageExplorer``
    (``supports=[ParquetByDuckDB]``): supports given are tried before the
    defaults. To view an item (the preview panel, "View in a new tab"), an
    explorer uses the first support for the format (``isinstance`` of
    ``format``) of the engine chosen (by the user, or the first of
    ``engine_preference``) whose packages are installed and whose
    ``supports`` says it views the item; "Preview as" offers the other
    engines. "Python code" shows the recipes of the first such support of
    each engine for "recipe".

    Rules for a subclass:

    - Implement ``view``, ``recipe`` or both. By default, ``supports`` says
      a support does what it implements, for every item.
    - Override ``supports`` to refuse items it cannot handle, e.g. an image
      format the library cannot read, or a storage the library cannot reach.
      It decides from the item's location, path and info, never by reading
      the storage: it runs for each item clicked.
    - Once ``supports`` has said yes, the explorer calls the method and
      tries no other support: what the method raises is shown as the item's
      error.
    - ``view()`` returns a ``QueryView`` of the data for the data browser
      (filters, sort, pages), or a view of what it read, e.g. a
      ``TableView`` of the first rows, a ``TextView``. A view holding
      something to release (a connection, a temporary file) releases it in
      a function given to its ``on_close()``, which the explorer calls once
      it no longer shows the view; until then, a ``QueryView``'s data must
      stay readable.
    - Before reading much, e.g. a whole large file, ``view()`` can ask the
      user first: it returns a ``ViewWithConfirmation``, a
      ``ViewWithChoice`` or a ``ViewWithInput``, whose function makes the
      view once the user answers.
    - Each method gets the detected format, then the item as an
      ``ItemContext`` (``ctx``): its location (where it is, for libraries
      doing their own I/O and for the code: ``ctx.url_or_local_path``, for Spark
      ``supports.pyspark.spark_url(ctx.location.url)``), the explorer's
      fsspec filesystem and the item's path in it (to read it through the
      explorer's filesystem: ``ctx.head_text(n)``, ``ctx.read_whole(limits)``),
      its info and listing, and whether it is a folder (``ctx.is_dir``); then
      its options, an ``options_model``.
    - Options are the fields of ``options_model`` (see ``SupportOptions``),
      never ``__init__`` arguments: explorers create supports without
      arguments, and give each the options of its engine's ``key``
      (``engine_options={"polars": {"*": {...}, "parquet": {...}}}``),
      those of its model's fields.
    - Import the packages through their ``PythonPackage``'s ``load()``, in the
      methods, never at the top of the module: they are optional.

    Attributes
    ----------
    format : type of DataFormat
        The format handled, e.g. ``Parquet``; its subclasses too.
    engine : type of Engine or None
        The library handling it, e.g. polars-support's ``PolarsEngine``: what users choose to
        view with, what "Python code" names, and the key of its options in
        ``engine_options`` (its ``key``, e.g. "polars"). None for the
        built-in views needing no package (text, JSON, images), used for the
        formats the engine chosen does not handle; they take no options.
    additional_requirements : tuple of PythonPackage
        Other packages it needs besides its engine's, as instances, e.g.
        ``(DeltaSpark(),)`` for Spark reading Delta Lake tables.
    options_model : type of SupportOptions, default SupportOptions
        Its options (see ``SupportOptions``); by default none.
    """

    # See the class docstring.
    format: ClassVar[type[DataFormat]]
    engine: ClassVar[type[Engine] | None] = None
    additional_requirements: ClassVar[tuple[PythonPackage, ...]] = ()
    options_model: ClassVar[type[SupportOptions]] = SupportOptions

    @classmethod
    def requirements(cls) -> tuple[PythonPackage, ...]:
        """All the packages it needs: its engine's (``Engine.requirements``),
        then ``additional_requirements``."""
        engine = cls.engine.requirements if cls.engine is not None else ()
        return (*engine, *cls.additional_requirements)

    @classmethod
    def is_installed(cls) -> bool:
        """Whether its engine and ``additional_requirements`` are installed."""
        return (cls.engine is None or cls.engine.is_installed()) and all(
            p.is_installed() for p in cls.additional_requirements
        )

    @classmethod
    def library(cls) -> str:
        """Its engine's ``key`` ("python" for the built-in views): its
        options' key in ``engine_options``."""
        return cls.engine.key if cls.engine is not None else "python"

    @classmethod
    def implements(cls, task: Task) -> bool:
        """Whether the class implements ``task``'s method (overrides
        ``FormatSupport``'s): what the explorer offers before knowing the
        item, e.g. the engines users choose from."""
        return getattr(cls, task) is not getattr(FormatSupport, task)

    def supports(
        self, fmt: DataFormat, ctx: ItemContext, options: SupportOptions, task: Task
    ) -> bool:
        """Whether it does ``task`` for the item: the explorer calls the
        method of a task only for the items it supports, and then tries no
        other support.

        Override it to refuse what the library cannot handle, e.g. an image
        format it cannot read, or a storage it cannot reach (from
        ``ctx.location``, maybe as the options say). It runs on the kernel's
        main thread for each item clicked, so it decides from the format, the
        location, the path, the info and the options: never by reading the
        storage.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``.
        ctx : ItemContext
            The file or folder (see ``view``).
        options : SupportOptions
            Its options for the item, an ``options_model``, as the method
            would get them.
        task : {"view", "recipe"}
            The method the explorer would call.

        Returns
        -------
        bool
            By default, whether the class implements the method
            (``implements``).

        Examples
        --------
        Code for the images Pillow opens, not SVG:

        >>> def supports(self, fmt, ctx, options, task):
        ...     svg = fmt.mime_type(ctx.path) == "image/svg+xml"
        ...     return super().supports(fmt, ctx, options, task) and not svg
        """
        return self.implements(task)

    def view(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        options: SupportOptions,
        limits: ViewLimits,
    ) -> View:
        """A view of the item, shown in the preview panel or a tab.

        A ``QueryView`` of the data opens it in the data browser: read it
        lazily where the format allows, as the browser only fetches the rows
        it shows. Libraries doing their own I/O (polars, DuckDB, Spark) read
        the location (``ctx.url_or_local_path``), with credentials from the
        environment or the options. Other views show what they read, mostly
        the beginning of the file through the explorer's filesystem
        (``ctx.head_text``, ``ctx.read_whole``), so any storage the explorer
        reaches can be viewed.

        The explorer calls it in a worker thread, so that a slow view (e.g.
        a Spark session starting) leaves the kernel free; meanwhile the
        preview or tab shows that it is loading. Views of other items may be
        made at the same time. It never touches widgets or displays anything.
        What the view holds is read later in other threads, one request at a
        time (e.g. the data browser's pages).

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``: what its
            ``matches`` found (e.g. a Parquet dataset's layout, by location).
        ctx : ItemContext
            The file or folder: where it is, the explorer's filesystem it is
            on (with its credentials) and its path there, its info and
            listing.
        options : SupportOptions
            Its options, an ``options_model``.
        limits : ViewLimits
            How much to read and show (bytes, rows).

        Returns
        -------
        View
            E.g. a ``QueryView`` of a LazyFrame, a ``TableView`` of the first
            rows, a ``TextView``; or a ``ViewWithConfirmation``,
            ``ViewWithChoice`` or ``ViewWithInput`` asking the user first.

        Raises
        ------
        NotImplementedError
            By default: a support viewing items implements it.
        """
        raise NotImplementedError

    def recipe(
        self, fmt: DataFormat, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        """The recipes' code: Python loading the data with the library, by
        title, shown in "Python code" under ``library()``.

        Titles say what the code does, without the library, which "Python
        code" shows already: e.g. "Load as LazyFrame", "Load as DataFrame".
        The code runs as it is in a new notebook: its imports first, and what
        else it needs, e.g. a Spark session. Installing the packages and
        configuring access to the storage are left to the user. It reads the
        location (``ctx.url_or_local_path``; for Spark,
        ``supports.pyspark.spark_url(ctx.location.url)``); reading the file
        is for what the code needs to know of it, e.g. a CSV file's
        separator.

        The predefined supports fill templates, class attributes
        ``*_template`` written with ``inspect.cleandoc`` just before the
        method, with ``str.format``: the URL (``{url}``, as a Python literal)
        and the keyword arguments set by the options (``{kwargs}``, with
        ``format_kwargs``, the options as ``options.code_value`` gives them).
        A subclass can change a template alone.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``.
        ctx : ItemContext
            The file or folder (see ``view``).
        options : SupportOptions
            Its options, an ``options_model``.

        Returns
        -------
        dict of str to str
            Title -> code, in the order shown, e.g. {"Load as LazyFrame":
            "import polars as pl\\n\\ndf = pl.scan_delta('s3://bucket/t')"}.

        Raises
        ------
        NotImplementedError
            By default: a support giving code implements it.
        """
        raise NotImplementedError
