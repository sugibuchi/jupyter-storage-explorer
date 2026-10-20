"""How to handle data in a format with a library: the ``FormatSupport``
interface, ``SupportChain``, by which explorers choose a support for each
capability, and the ``Recipe`` of a support's code (the predefined supports
are in supports/, a module per library: polars.py, pandas.py, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias

from jupyter_storage_explorer.formats.view import InstallView

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
    from jupyter_storage_explorer.formats.package import PythonPackage
    from jupyter_storage_explorer.formats.view import View, ViewLimits

# What a support can do with a format's data, each the name of the method
# doing it: view it (the preview panel, a tab), give recipes, the code
# loading it ("Python code").
Capability: TypeAlias = Literal["view", "recipe"]


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
      something to release (a connection, a temporary file) is given it as
      ``on_close``, which the explorer calls once it no longer shows the
      view; until then, a ``QueryView``'s data must stay readable.
    - A method may raise ``NotSupported`` for a particular item (e.g. an
      image format the library cannot read): the next support is then
      tried, and for "recipe", the support's code is left out.
    - Each method gets the detected format, then the item as an
      ``ItemContext`` (``ctx``): its location (where it is, for libraries
      doing their own I/O and for the code: ``library_url(ctx.location)``,
      for Spark ``supports.pyspark.spark_url(ctx.location.url)``), the
      explorer's fsspec filesystem and the item's path in it (to read it
      through the explorer's filesystem, e.g. with ``head_text(ctx.fs,
      ctx.path, n)``), its info and listing, and whether it is a folder
      (``ctx.is_dir``).
    - Options are keyword-only arguments of ``__init__``. Explorers create
      the supports given as classes with the options of their ``engine``'s
      package (``format_options={"polars": {"*": {...}, "parquet":
      {...}}}``), passing each only those its ``__init__`` takes; supports
      given as objects are used as they are.
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
    """

    class NotSupported(Exception):
        """Raised by a capability's method for an item it cannot handle: the
        next support is tried."""

    # See the class docstring.
    format: ClassVar[type[DataFormat]]
    engine: ClassVar[type[PythonPackage] | None] = None
    additional_requirements: ClassVar[tuple[type[PythonPackage], ...]] = ()
    capabilities: ClassVar[tuple[Capability, ...]] = ()

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

    def view(self, fmt: DataFormat, ctx: ItemContext, *, limits: ViewLimits) -> View:
        """A view of the item, shown in the preview panel or a tab.

        A ``QueryView`` of the data opens it in the data browser: read it
        lazily where the format allows, as the browser only fetches the rows
        it shows. Libraries doing their own I/O (polars, DuckDB, Spark) read
        the location (``library_url(ctx.location)``), with credentials from
        the environment or the options. Other views show what they read,
        mostly the beginning of the file through ``ctx.fs`` (``head_text``,
        ``read_whole`` in ``formats.base``), so any storage the explorer
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

    def recipe(self, fmt: DataFormat, ctx: ItemContext) -> dict[str, str]:
        """The recipes' code: Python loading the data with the library, by
        title, shown in "Python code" under ``library()``.

        Titles say what the code does, without the library, which "Python
        code" shows already: e.g. "Load as LazyFrame", "Load as DataFrame".
        The code runs as it is in a new notebook: its imports first, and what
        else it needs, e.g. a Spark session. Installing the packages and
        configuring access to the storage are left to the user. It reads the
        location (``library_url(ctx.location)``; for Spark,
        ``supports.pyspark.spark_url(ctx.location.url)``); ``ctx.fs`` and
        ``ctx.path`` are for what the code needs to know of the file, e.g. a
        CSV file's separator.

        The predefined supports fill templates, class attributes
        ``*_template`` written with ``inspect.cleandoc`` just before the
        method, with ``str.format``: the URL (``{url}``, as a Python literal)
        and the keyword arguments set by the options (``{kwargs}``, with
        ``format_kwargs``; storage options through ``snippet_options``). A
        subclass can change a template alone.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``.
        ctx : ItemContext
            The file or folder (see ``view``).

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
    """The supports of an explorer, in order, and what is done with them:
    for each capability, the first support for the format that is installed
    and has it (see ``FormatSupport``)."""

    def __init__(self, supports: Iterable[FormatSupport]) -> None:
        self.supports = list(supports)

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

    def view(self, fmt: DataFormat, ctx: ItemContext, *, limits: ViewLimits) -> View:
        """The view of the first support installed that views the item (see
        ``FormatSupport.view``); with none installed, what to install
        (``InstallView``). ValueError if none can view it."""
        for support in self.installed(fmt, "view"):
            try:
                return support.view(fmt, ctx, limits=limits)
            except FormatSupport.NotSupported:
                continue
        missing = [s for s in self.of(fmt, "view") if not s.is_installed()]
        if not missing:
            raise ValueError(f"{ctx.name} cannot be viewed as {fmt.label}")
        options: list[list[str]] = []
        for support in missing:
            packages = [
                r.package for r in support.requirements() if not r().is_installed()
            ]
            if packages not in options:
                options.append(packages)
        return InstallView(format=fmt.label, options=options)

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
            try:
                codes = support.recipe(fmt, ctx)
            except FormatSupport.NotSupported:
                continue
            libraries.add(support.library())
            recipes += [
                Recipe(title=title, requirements=support.requirements(), code=code)
                for title, code in codes.items()
            ]
        return recipes
