"""How to handle data in a format with a library: the ``FormatSupport``
interface, and ``SupportChain``, by which explorers choose a support for
each capability (the predefined supports are in supports/, a module per
library: polars.py, pandas.py, ...)."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

from jupyter_storage_explorer.formats.base import Recipe, name_of
from jupyter_storage_explorer.formats.preview import InstallPreview

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits
    from jupyter_storage_explorer.formats.requirement import (
        Requirement,
        Requirements,
    )
    from jupyter_storage_explorer.location import Location

# What a support can do with a format's data, each the name of the method
# doing it: preview it, query it in the data browser, give a recipe, the code
# loading it ("Python code").
Capability: TypeAlias = Literal["preview", "query", "recipe"]


class FormatSupport:
    """How to preview, query or load the data of one format with one library.

    Subclass it to handle a format with a library of your own, e.g. Parquet
    with DuckDB, and give it to ``StorageExplorer``
    (``supports=[ParquetByDuckDB]``): supports given are tried before the
    defaults. For previews and the data browser, an explorer uses the first
    support for the format (``isinstance`` of ``format``) whose packages are
    installed and that lists the capability in ``capabilities``; "Python
    code" shows the recipe of the first support listing "recipe" of each
    library, installed or not.

    Rules for a subclass:

    - List in ``capabilities`` the name of every method the class
      implements: "preview", "query", "recipe". The explorer reads only
      ``capabilities`` to decide what to offer: a method not listed there is
      never called, and a capability listed there must have its method
      implemented. A subclass adding a method extends ``capabilities``.
    - A method may raise ``NotSupported`` for a particular item (e.g. an
      image format the library cannot read): the next support is then
      tried, and for "recipe", the support's code is left out.
    - Each method gets the item as its location (where it is, for libraries
      doing their own I/O and for the code: ``library_url(location)``,
      ``spark_url(location.url)``), the explorer's fsspec filesystem and the
      item's path in it (to read it through the explorer's filesystem, e.g.
      with ``head_text(fs, path, n)``), and whether it is a folder.
    - Options are keyword-only arguments of ``__init__``. Explorers create
      the supports given as classes with the options of their ``use``'s
      package (``format_options={"polars": {"*": {...}, "parquet":
      {...}}}``), passing each only those its ``__init__`` takes; supports
      given as objects are used as they are.
    - Import the packages through their ``Requirement``'s ``load()``, in the
      methods, never at the top of the module: they are optional.

    Attributes
    ----------
    format : type of DataFormat
        The format handled, e.g. ``Parquet``; its subclasses too.
    use : type of Requirement or None
        The package (library) handling it, e.g. ``Polars``: what "Python
        code" names the support's code by, and the key of its options in
        ``format_options`` (its ``package``, e.g. "polars"). None for a
        support needing no package (e.g. text previewed by Python itself),
        which takes no options.
    additional_requirements : tuple of Requirement classes
        Other packages it needs, e.g. ``(DeltaSpark,)`` for Spark reading
        Delta Lake tables.
    capabilities : tuple of str
        The methods it implements: "preview", "query", "recipe" (see above).
    """

    class NotSupported(Exception):
        """Raised by a capability's method for a target it cannot handle: the next
        support is tried."""

    # See the class docstring.
    format: ClassVar[type[DataFormat]]
    use: ClassVar[type[Requirement] | None] = None
    additional_requirements: ClassVar[Requirements] = ()
    capabilities: ClassVar[tuple[Capability, ...]] = ()

    @classmethod
    def requirements(cls) -> Requirements:
        """``use`` and ``additional_requirements``: all the packages it needs."""
        return (
            *((cls.use,) if cls.use is not None else ()),
            *cls.additional_requirements,
        )

    @classmethod
    def is_installed(cls) -> bool:
        """Whether all of ``requirements()`` are installed in the kernel."""
        return all(r().is_installed() for r in cls.requirements())

    @classmethod
    def library(cls) -> str:
        """The name "Python code" shows its code under: ``use``'s package."""
        return cls.use.package if cls.use is not None else "python"

    def preview(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        """What to show in the preview panel.

        Most previews read the beginning of the file through ``fs``
        (``head_text``, ``read_whole`` in ``formats.base``), so any storage
        the explorer reaches can be previewed; a library reading by URL
        (e.g. polars for Delta Lake) reads ``library_url(location)``.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``: what its
            ``matches`` found (e.g. a Parquet dataset's layout, by location).
        location : Location
            Where the file or folder is, as libraries reading it themselves
            take it.
        fs : AbstractFileSystem
            The explorer's filesystem it is on, with its credentials.
        path : str
            Its path in ``fs``.
        is_dir : bool
            Whether it is a folder (e.g. a table) or a file.
        limits : PreviewLimits
            How much to read and show (bytes, rows).

        Returns
        -------
        Preview
            E.g. a ``TablePreview`` of the first rows, a ``TextPreview``.

        Raises
        ------
        FormatSupport.NotSupported
            By default, or for an item it cannot preview.
        """
        raise self.NotSupported

    def query(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> Any:
        """The data, lazily, for the data browser ("Query data").

        Read lazily where the format allows: the browser only fetches the
        rows it shows. Libraries doing their own I/O (polars, DuckDB, Spark)
        read the location (``library_url(location)``), with credentials from
        the environment or the options; others can read through ``fs``.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``.
        location : Location
            Where the file or folder is.
        fs : AbstractFileSystem
            The explorer's filesystem it is on.
        path : str
            Its path in ``fs``.
        is_dir : bool
            Whether it is a folder (e.g. a table) or a file.

        Returns
        -------
        Any
            Any dataframe narwhals supports, e.g. a polars LazyFrame.

        Raises
        ------
        FormatSupport.NotSupported
            By default, or for data it cannot query.
        """
        raise self.NotSupported

    def recipe(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        """The recipe's code: Python loading the data with the library, shown
        in "Python code" under ``library()``.

        The code runs as it is in a new notebook: its imports first, and what
        else it needs, e.g. a Spark session. Installing the packages and
        configuring access to the storage are left to the user. It reads the
        location (``library_url(location)``, ``spark_url(location.url)``);
        ``fs`` and ``path`` are for what the code needs to know of the file,
        e.g. a CSV file's separator.

        The predefined supports fill a template, a class attribute
        ``recipe_template`` written with ``inspect.cleandoc`` just before
        the method, with ``str.format``: the URL (``{url}``, as a Python
        literal) and the keyword arguments set by the options (``{kwargs}``,
        with ``format_kwargs``; storage options through ``snippet_options``).
        A subclass can change the template alone.

        Parameters
        ----------
        fmt : DataFormat
            The format detected, an instance of ``format``.
        location : Location
            Where the file or folder is.
        fs : AbstractFileSystem
            The explorer's filesystem it is on.
        path : str
            Its path in ``fs``.
        is_dir : bool
            Whether it is a folder (e.g. a table) or a file.

        Returns
        -------
        str
            E.g. ``import polars as pl``, a blank line and
            ``df = pl.scan_delta('s3://bucket/table')``.

        Raises
        ------
        FormatSupport.NotSupported
            By default, or for an item it has no code for.
        """
        raise self.NotSupported


def support_options(cls: type[FormatSupport]) -> frozenset[str]:
    """The options a support class takes: its ``__init__``'s keyword-only
    arguments."""
    parameters = inspect.signature(cls.__init__).parameters.values()
    return frozenset(p.name for p in parameters if p.kind is p.KEYWORD_ONLY)


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

    def can_query(self, fmt: DataFormat) -> bool:
        """Whether the data browser can query ``fmt``: a support installed does it."""
        return bool(self.installed(fmt, "query"))

    def preview(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        """The preview of the first support installed that previews the
        item (see ``FormatSupport.preview``); with none installed, what to
        install (``InstallPreview``). ValueError if none can preview it."""
        for support in self.installed(fmt, "preview"):
            try:
                return support.preview(fmt, location, fs, path, is_dir, limits=limits)
            except FormatSupport.NotSupported:
                continue
        missing = [s for s in self.of(fmt, "preview") if not s.is_installed()]
        if not missing:
            raise ValueError(f"{name_of(path)} cannot be previewed as {fmt.label}")
        options: list[list[str]] = []
        for support in missing:
            packages = [
                r.package for r in support.requirements() if not r().is_installed()
            ]
            if packages not in options:
                options.append(packages)
        return InstallPreview(format=fmt.label, options=options)

    def query(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> Any:
        """The data of the first support installed that queries the item
        (see ``FormatSupport.query``). ValueError if none can."""
        for support in self.installed(fmt, "query"):
            try:
                return support.query(fmt, location, fs, path, is_dir)
            except FormatSupport.NotSupported:
                continue
        raise ValueError(f"{fmt.label} cannot be queried")

    def recipes(
        self,
        fmt: DataFormat,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> list[Recipe]:
        """The recipes of the supports with "recipe" for ``fmt``, installed or
        not (the code may run elsewhere): of each library, the first that
        supports the item, so a support given before the defaults replaces
        the default one of its library."""
        recipes: dict[str, Recipe] = {}
        for support in self.of(fmt, "recipe"):
            if support.library() in recipes:
                continue
            try:
                code = support.recipe(fmt, location, fs, path, is_dir)
            except FormatSupport.NotSupported:
                continue
            recipes[support.library()] = Recipe(
                requirements=support.requirements(), code=code
            )
        return list(recipes.values())
