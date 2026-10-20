"""How to handle data in a format with a library: the ``FormatSupport``
interface, with ``SupportOptions``, the base of its options;
``SupportChain``, by which explorers choose a support for each capability
and give each its options (``format_options``); and the ``Recipe`` of a
support's code (the predefined supports are in supports/, a module per
library: polars.py, pandas.py, ...)."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

from jupyter_storage_explorer.formats.view import InstallView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.view import View, ViewLimits
    from jupyter_storage_explorer.location import Location

# What a support can do with a format's data, each the name of the method
# doing it: view it (the preview panel, a tab), give recipes, the code
# loading it ("Python code").
Capability: TypeAlias = Literal["view", "recipe"]

# In format_options, the options of a library for all formats.
ALL_FORMATS = "*"

# StorageExplorer's format_options: {library: {format name or "*": options}},
# the options a dict, or a function of the item's location returning one
# (see SupportChain).
FormatOptions: TypeAlias = "Mapping[str, Mapping[str, Mapping[str, Any] | Callable[[Location], Mapping[str, Any]]]]"


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


@dataclass(frozen=True, kw_only=True)
class SupportOptions:
    """The options of a support: none. The base of supports' options.

    A support taking options names a subclass as its ``options_model``: a
    frozen, keyword-only dataclass whose fields are the options, each with a
    default, as users may set none of them. Explorers make one from
    ``format_options`` and pass it to each of the support's methods.
    Subclasses of a library's options share them, e.g. its storage options,
    which ``format_options``' ``"*"`` then sets for all its formats.

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
    ...     format_options={"duckdb": {"*": {"config": {"threads": 4}}}},
    ... )
    """

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


class FormatSupport:
    """How to view or load the data of one format with one library.

    Subclass it to handle a format with a library of your own, e.g. Parquet
    with DuckDB, and give it to ``StorageExplorer``
    (``supports=[ParquetByDuckDB]``): supports given are tried before the
    defaults. To view an item (the preview panel, "View in a new tab"), an
    explorer uses the first support for the format (``isinstance`` of
    ``format``) whose packages are installed and that lists "view" in
    ``capabilities``; "Python code" shows the recipes of the first support
    listing "recipe" of each library, installed or not.

    Rules for a subclass:

    - List in ``capabilities`` the name of every method the class
      implements: "view", "recipe". The explorer reads only
      ``capabilities`` to decide what to offer: a method not listed there is
      never called, and a capability listed there must have its method
      implemented. A subclass adding a method extends ``capabilities``.
    - ``view()`` returns a ``QueryView`` of the data for the data browser
      (filters, sort, pages), or a view of what it read, e.g. a
      ``TableView`` of the first rows, a ``TextView``. A view holding
      something to release (a connection, a temporary file) releases it in
      a function given to its ``on_close()``, which the explorer calls once
      it no longer shows the view; until then, a ``QueryView``'s data must
      stay readable.
    - A method may raise ``NotSupported`` for a particular item (e.g. an
      image format the library cannot read): the next support is then
      tried, and for "recipe", the support's code is left out.
    - Each method gets the detected format, then the item as an
      ``ItemContext`` (``ctx``): its location (where it is, for libraries
      doing their own I/O and for the code: ``ctx.library_url``, for Spark
      ``supports.pyspark.spark_url(ctx.location.url)``), the explorer's
      fsspec filesystem and the item's path in it (to read it through the
      explorer's filesystem: ``ctx.head_text(n)``, ``ctx.read_whole(limits)``),
      its info and listing, and whether it is a folder (``ctx.is_dir``); then
      its options, an ``options_model``.
    - Options are the fields of ``options_model`` (see ``SupportOptions``),
      never ``__init__`` arguments: explorers create supports without
      arguments, and give each the options of its ``engine``'s package
      (``format_options={"polars": {"*": {...}, "parquet": {...}}}``),
      those of its model's fields.
    - Import the packages through their ``PythonPackage``'s ``load()``, in the
      methods, never at the top of the module: they are optional.

    Attributes
    ----------
    format : type of DataFormat
        The format handled, e.g. ``Parquet``; its subclasses too.
    engine : type of PythonPackage or None
        The package (library) handling it, e.g. ``Polars``: what "Python
        code" groups the support's recipes under, and the key of its options
        in ``format_options`` (its ``package``, e.g. "polars"). None for a
        support needing no package (e.g. text viewed by Python itself),
        which takes no options.
    additional_requirements : tuple of PythonPackage classes
        Other packages it needs, e.g. ``(DeltaSpark,)`` for Spark reading
        Delta Lake tables.
    capabilities : tuple of str
        The methods it implements: "view", "recipe" (see above).
    options_model : type of SupportOptions, default SupportOptions
        Its options (see ``SupportOptions``); by default none.
    """

    class NotSupported(Exception):
        """Raised by a capability's method for an item it cannot handle: the
        next support is tried."""

    # See the class docstring.
    format: ClassVar[type[DataFormat]]
    engine: ClassVar[type[PythonPackage] | None] = None
    additional_requirements: ClassVar[tuple[type[PythonPackage], ...]] = ()
    capabilities: ClassVar[tuple[Capability, ...]] = ()
    options_model: ClassVar[type[SupportOptions]] = SupportOptions

    @classmethod
    def requirements(cls) -> tuple[type[PythonPackage], ...]:
        """``engine`` and ``additional_requirements``: all the packages it needs."""
        return (
            *((cls.engine,) if cls.engine is not None else ()),
            *cls.additional_requirements,
        )

    @classmethod
    def is_installed(cls) -> bool:
        """Whether all of ``requirements()`` are installed in the kernel."""
        return all(r().is_installed() for r in cls.requirements())

    @classmethod
    def library(cls) -> str:
        """The library "Python code" groups its recipes under: ``engine``'s package."""
        return cls.engine.package if cls.engine is not None else "python"

    @classmethod
    def option_names(cls) -> frozenset[str]:
        """The options it takes: the fields of ``options_model``."""
        return frozenset(f.name for f in dataclasses.fields(cls.options_model))

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
        the location (``ctx.library_url``), with credentials from the
        environment or the options. Other views show what they read, mostly
        the beginning of the file through the explorer's filesystem
        (``ctx.head_text``, ``ctx.read_whole``), so any storage the explorer
        reaches can be viewed.

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
            rows, a ``TextView``.

        Raises
        ------
        FormatSupport.NotSupported
            By default, or for an item it cannot view.
        """
        raise self.NotSupported

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
        location (``ctx.library_url``; for Spark,
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
        FormatSupport.NotSupported
            By default, or for an item it has no code for.
        """
        raise self.NotSupported


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
        taken = support.option_names()
        return support.options_model(**{k: v for k, v in merged.items() if k in taken})

    def of(self, fmt: DataFormat, capability: Capability) -> list[FormatSupport]:
        """The supports with ``capability`` for ``fmt``, installed or not, in
        order."""
        return [
            s
            for s in self.supports
            if isinstance(fmt, s.format) and capability in s.capabilities
        ]

    def installed(self, fmt: DataFormat, capability: Capability) -> list[FormatSupport]:
        """The supports with ``capability`` for ``fmt`` whose packages are
        installed."""
        return [s for s in self.of(fmt, capability) if s.is_installed()]

    def view(self, fmt: DataFormat, ctx: ItemContext, limits: ViewLimits) -> View:
        """The view of the first support installed that views the item (see
        ``FormatSupport.view``); with none installed, what to install
        (``InstallView``). ValueError if none can view it."""
        for support in self.installed(fmt, "view"):
            options = self.options_of(support, ctx.location)
            try:
                return support.view(fmt, ctx, options, limits)
            except FormatSupport.NotSupported:
                continue
        missing = [s for s in self.of(fmt, "view") if not s.is_installed()]
        if not missing:
            raise ValueError(f"{ctx.name} cannot be viewed as {fmt.label}")
        packages_missing: list[list[str]] = []
        for support in missing:
            packages = [
                r.package for r in support.requirements() if not r().is_installed()
            ]
            if packages not in packages_missing:
                packages_missing.append(packages)
        return InstallView(format=fmt.label, options=packages_missing)

    def recipes(self, fmt: DataFormat, ctx: ItemContext) -> list[Recipe]:
        """The recipes of the supports with "recipe" for ``fmt``, installed or
        not (the code may run elsewhere): of each library, those of the first
        support that has code for the item, so a support given before the
        defaults replaces the default one of its library."""
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
            taken |= support.option_names()
    unknown = values.keys() - taken
    if unknown:
        raise ValueError(
            f"{where}: unknown options {sorted(unknown)}; choose from {sorted(taken)}"
        )
