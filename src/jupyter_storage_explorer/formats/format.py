"""How to detect, preview and load each kind of data: the ``DataFormat``
interface, and the ``Target`` it reads (the predefined formats each have a
module: delta.py, parquet.py, text.py, ...)."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer.formats.preview import InstallPreview

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits
    from jupyter_storage_explorer.formats.requirement import Requirements


@dataclass(frozen=True, kw_only=True)
class Target:
    """A file or directory selected in the browser."""

    fs: AbstractFileSystem
    path: str
    # Location to use in generated code and for libraries to read, e.g.
    # "s3://bucket/key"; set by StorageExplorer._url.
    url: str
    info: Mapping[str, Any]
    # Listing of the directory (fsspec ``ls(detail=True)`` entries); None for files.
    children: Sequence[Mapping[str, Any]] | None = None

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def name(self) -> str:
        return self.path.rstrip("/").rsplit("/", 1)[-1]

    @property
    def size(self) -> int | None:
        return self.info.get("size")

    @property
    def child_names(self) -> set[str]:
        return {c["name"].rstrip("/").rsplit("/", 1)[-1] for c in self.children or ()}

    def child_path(self, name: str) -> str:
        return f"{self.path.rstrip('/')}/{name}"

    def head(self, size: int) -> bytes:
        """The first ``size`` bytes of the file, without reading the rest."""
        with self.fs.open(self.path, "rb") as f:
            return f.read(size)

    def read_whole(self, limits: PreviewLimits) -> bytes:
        """The whole file, for formats that cannot be read in part."""
        if self.size is not None and self.size > limits.max_whole_file_bytes:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to preview (over {limit} MB)")
        return self.fs.cat_file(self.path)

    def head_text(self, size: int) -> tuple[str, bool]:
        """The first ``size`` bytes decoded as UTF-8, and whether the file is longer.

        When the file is longer, the text is cut after its last complete line.
        """
        data = self.head(size + 1)
        truncated = len(data) > size
        if truncated:
            data = data[:size]
            if (end := data.rfind(b"\n")) >= 0:
                data = data[: end + 1]
        return data.decode("utf-8-sig", errors="replace"), truncated


@dataclass(frozen=True, kw_only=True)
class Recipe:
    """One way to load the data in a notebook, e.g. with polars or with pandas."""

    library: str  # label shown to the user, e.g. "polars"
    # The imports, then the loading code. Installing the packages and
    # configuring access to the storage are left to the user: reaching a data
    # lake often needs configuration that depends on it.
    code: str


# The icons a format's files can have in the explorer's list (``file_icon``):
# JupyterLab's file icons, FILE_ICON_SVGS in static/icons.js.
FILE_ICONS = (
    "file",
    "notebook",
    "markdown",
    "pdf",
    "python",
    "json",
    "julia",
    "spreadsheet",
    "r-kernel",
    "yaml",
    "image",
    "audio",
    "video",
    "html5",
)


class DataFormat(abc.ABC):
    """How to recognise, preview and load one kind of file or directory.

    Subclass it for a format of your own, and give it to ``StorageExplorer``
    (``formats=[MyFormat(), *default_formats()]``). File formats usually only
    set ``extensions``; directory formats (Delta Lake tables, Spark output,
    Hive-partitioned datasets, ...) override ``matches`` and inspect
    ``target.children``. Implement ``preview`` and ``load_code``, and
    ``scan`` to be queryable.

    A format with options takes them in ``__init__`` as keyword-only
    arguments, and ignores others in ``**kwargs``: explorers create every
    default format with all of ``format_options`` (see ``default_formats``).
    Options are named after the library they are for, and those for one
    format only also after the format, e.g. ``polars_storage_options`` and
    ``polars_delta_use_pyarrow``.

    Attributes
    ----------
    name : str
        Identifier, lower case with "-" between words, e.g. "delta": chooses
        a format (``DataExplorer``, "Preview as"), and in CSS
        (``[data-file-format]``).
    label : str
        Shown to the user, e.g. "Delta Lake table".
    priority : int, default 0
        When several formats match (a Delta table is also a folder of
        Parquet files), the highest wins.
    extensions : tuple of str
        Lower-case file name endings, e.g. ``(".parquet",)``, used by the
        default ``matches``.
    file_icon : str, tuple of (str, str), or None, default None
        The icon of the format's files in the explorer's list: one of
        ``FILE_ICONS`` (JupyterLab's file icons), e.g. "spreadsheet"; or an
        icon of your own, ``(name, svg)``: a name not in ``FILE_ICONS``, e.g.
        "avro", and an SVG image (its markup, ``"<svg ...>...</svg>"``, best
        square, e.g. with ``viewBox="0 0 24 24"``), shown as an image, so its
        scripts never run. None: the icon JupyterLab gives the file's
        extension, else a plain file. Folders always have the folder icon.
    preferred_requirements : tuple of tuples of Requirement classes
        Sets of packages that can read the format, most preferred first,
        e.g. ``((Polars, DeltaLake), (Pandas,))``: previews use the first set
        installed (none installed, the explorer tells what to install), and
        each set yields a "Python code" recipe. Empty for a format previewed
        without packages.
    code_only_requirements : tuple of tuples of Requirement classes
        Sets of packages only in recipes, after the others, e.g.
        ``((PySpark,),)``; previews never use them.
    query_requirements : tuple of Requirement classes
        Packages needed for the data browser ("Query data"), e.g.
        ``(Polars, DeltaLake)``; empty if the format cannot be queried.
    """

    # See the class docstring.
    name: ClassVar[str]
    label: ClassVar[str]
    priority: ClassVar[int] = 0
    extensions: ClassVar[tuple[str, ...]] = ()
    file_icon: ClassVar[str | tuple[str, str] | None] = None
    preferred_requirements: ClassVar[tuple[Requirements, ...]] = ()
    code_only_requirements: ClassVar[tuple[Requirements, ...]] = ()
    query_requirements: ClassVar[Requirements] = ()

    def matches(self, target: Target) -> bool:
        """Whether a file or folder is in this format.

        Called on every click, so it must be cheap: look at the name, or the
        folder's listing (``target.children``), not at the contents.

        Parameters
        ----------
        target : Target
            The file or folder.

        Returns
        -------
        bool
            By default: a file whose name ends with one of ``extensions``.
        """
        return not target.is_dir and target.name.lower().endswith(self.extensions)

    @abc.abstractmethod
    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        """The sections to show in the preview panel.

        Only called with packages installed: when none of
        ``preferred_requirements`` is, the explorer shows ``install_hint()``
        instead.

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``.
        limits : PreviewLimits
            How much to read and show (bytes, rows).
        requirements : tuple of Requirement classes
            The packages to preview with: the first of
            ``preferred_requirements`` installed (``installed_requirements``),
            e.g. ``(Polars,)``; empty if the format has none.

        Returns
        -------
        list of Preview
            E.g. a ``TablePreview`` of the first rows, a ``TextPreview``.
        """

    def can_query(self) -> bool:
        """Whether the data browser can query this format.

        Returns
        -------
        bool
            True if it has ``query_requirements`` and they are all installed.
        """
        return bool(self.query_requirements) and all(
            r().is_installed() for r in self.query_requirements
        )

    def scan(self, url: str, is_dir: bool) -> Any:
        """The data, lazily, for the data browser ("Query data").

        Only called when ``can_query()``. Read lazily where the format allows:
        the browser only fetches the rows it shows.

        Parameters
        ----------
        url : str
            A location polars reads itself: a local path or a cloud URL (e.g.
            "s3://bucket/key"), with credentials from the environment.
        is_dir : bool
            Whether it is a folder (e.g. a table) or a file.

        Returns
        -------
        polars.LazyFrame
            Or any dataframe narwhals supports.

        Raises
        ------
        NotImplementedError
            By default: the format cannot be queried.
        """
        raise NotImplementedError(f"{self.label} cannot be queried")

    def installed_requirements(self) -> Requirements | None:
        """The packages to preview with.

        Returns
        -------
        tuple of Requirement classes, or None
            The first of ``preferred_requirements`` whose packages are all
            installed; None if there is none; empty if the format has none.
        """
        if not self.preferred_requirements:
            return ()
        for requirements in self.preferred_requirements:
            if all(r().is_installed() for r in requirements):
                return requirements
        return None

    def install_hint(self) -> list[Preview]:
        """A preview telling the user what to install to see this format.

        Returns
        -------
        list of Preview
            An ``InstallPreview`` with, per set of ``preferred_requirements``,
            the packages missing.
        """
        options = [
            [r.package for r in requirements if not r().is_installed()]
            for requirements in self.preferred_requirements
        ]
        return [InstallPreview(format=self.label, options=options)]

    @abc.abstractmethod
    def load_code(self, target: Target, requirements: Requirements) -> str:
        """Python code loading the data with one set of packages ("Python code").

        The code runs as it is in a new notebook: its imports first, and what
        else it needs, e.g. a Spark session. Installing the packages and
        configuring access to the storage are left to the user.

        The predefined formats only choose here, by the requirements, a
        method per set of packages named after its first one
        (``load_code_polars``, ``load_code_pandas``, ...), even when there is
        one. Each fills a template, a class attribute named after it
        (``load_code_polars_template``, written with ``inspect.cleandoc``),
        with ``str.format``: the URL (``{url}``, as a Python literal) and the
        keyword arguments set by the options (``{kwargs}``, with
        ``format_kwargs``; storage options through ``snippet_options``). A
        subclass can change a template alone.

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``; ``target.url`` is its
            location.
        requirements : tuple of Requirement classes
            One of ``preferred_requirements`` or ``code_only_requirements``.

        Returns
        -------
        str
            E.g. ``import polars as pl``, a blank line and
            ``df = pl.scan_delta('s3://bucket/table')``.
        """

    def recipes(self, target: Target) -> list[Recipe]:
        """The ways to load a file or folder in a notebook ("Python code").

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``.

        Returns
        -------
        list of Recipe
            One per set of ``preferred_requirements`` and then of
            ``code_only_requirements``, with its ``load_code``.
        """
        return [
            Recipe(
                library=requirements[0].package,
                code=self.load_code(target, requirements),
            )
            for requirements in (
                *self.preferred_requirements,
                *self.code_only_requirements,
            )
        ]


def matching_formats(target: Target, formats: Iterable[DataFormat]) -> list[DataFormat]:
    """All formats that match ``target``, highest priority first (ties keep their order)."""
    return sorted((f for f in formats if f.matches(target)), key=lambda f: -f.priority)


def detect(target: Target, formats: Iterable[DataFormat]) -> DataFormat | None:
    """The highest-priority format that matches ``target``, if any.

    On a tie, the format listed first wins.
    """
    best = None
    for fmt in formats:
        if not fmt.matches(target):
            continue
        if best is None or fmt.priority > best.priority:
            best = fmt
    return best
