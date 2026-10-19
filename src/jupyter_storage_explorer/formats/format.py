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
    """How to recognise, preview, query and load one kind of file or directory.

    Subclass it for a format of your own, and give it to ``StorageExplorer``
    (``formats=[MyFormat(), *default_formats()]``). File formats usually only
    set ``extensions``; directory formats (Delta Lake tables, Spark output,
    Hive-partitioned datasets, ...) override ``matches`` and inspect
    ``target.children``. Implement ``preview`` and ``load_code``, and
    ``query`` to be queryable.

    Each of ``preview``, ``query`` and ``load_code`` is given the packages to
    use, one of the sets of its requirements (``preview_requirements``,
    ``query_requirements``, ``code_requirements``). With several sets, the
    predefined formats only choose there a method per set, named after its
    first package (``preview_polars``, ``preview_pandas``; ``load_code_polars``
    filling ``load_code_polars_template``, ...); with one, they implement it
    directly.

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
    preview_requirements : tuple of tuples of Requirement classes
        Sets of packages that can preview the format, most preferred first,
        e.g. ``((Polars,), (Pandas, PyArrow))``: ``preview`` is given the
        first set installed; with none installed, the explorer tells what to
        install instead. Empty for a format previewed without packages.
    query_requirements : tuple of tuples of Requirement classes
        Sets of packages that can query the format in the data browser
        ("Query data"), most preferred first, e.g. ``((Polars, DeltaLake),)``:
        ``query`` is given the first set installed. Empty if the format cannot
        be queried.
    code_requirements : tuple of tuples of Requirement classes
        Sets of packages the "Python code" loads the data with, e.g.
        ``((Polars,), (Pandas,), (PySpark,))``: a recipe each, whether
        installed or not.
    """

    # See the class docstring.
    name: ClassVar[str]
    label: ClassVar[str]
    priority: ClassVar[int] = 0
    extensions: ClassVar[tuple[str, ...]] = ()
    file_icon: ClassVar[str | tuple[str, str] | None] = None
    preview_requirements: ClassVar[tuple[Requirements, ...]] = ()
    query_requirements: ClassVar[tuple[Requirements, ...]] = ()
    code_requirements: ClassVar[tuple[Requirements, ...]] = ()

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
        ``preview_requirements`` is, the explorer shows ``install_hint()``
        instead.

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``.
        limits : PreviewLimits
            How much to read and show (bytes, rows).
        requirements : tuple of Requirement classes
            The packages to preview with, the first set of
            ``preview_requirements`` installed, e.g. ``(Polars,)``; empty if
            the format has none.

        Returns
        -------
        list of Preview
            E.g. a ``TablePreview`` of the first rows, a ``TextPreview``.
        """

    def query(self, url: str, is_dir: bool, requirements: Requirements) -> Any:
        """The data, lazily, for the data browser ("Query data").

        Only called when ``can_query()``. Read lazily where the format allows:
        the browser only fetches the rows it shows.

        Parameters
        ----------
        url : str
            A location the packages read themselves: a local path or a cloud
            URL (e.g. "s3://bucket/key"), with credentials from the
            environment.
        is_dir : bool
            Whether it is a folder (e.g. a table) or a file.
        requirements : tuple of Requirement classes
            The packages to query with, the first set of
            ``query_requirements`` installed, e.g. ``(Polars,)``.

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

    @abc.abstractmethod
    def load_code(self, target: Target, requirements: Requirements) -> str:
        """Python code loading the data with one set of packages ("Python code").

        The code runs as it is in a new notebook: its imports first, and what
        else it needs, e.g. a Spark session. Installing the packages and
        configuring access to the storage are left to the user.

        The predefined formats fill a template, a class attribute
        (``load_code_template``; with several sets, one per set:
        ``load_code_polars_template`` for ``load_code_polars``, ...), written
        with ``inspect.cleandoc``, with ``str.format``: the URL (``{url}``, as
        a Python literal) and the keyword arguments set by the options
        (``{kwargs}``, with ``format_kwargs``; storage options through
        ``snippet_options``). A subclass can change a template alone.

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``; ``target.url`` is its
            location.
        requirements : tuple of Requirement classes
            One of ``code_requirements``.

        Returns
        -------
        str
            E.g. ``import polars as pl``, a blank line and
            ``df = pl.scan_delta('s3://bucket/table')``.
        """

    @staticmethod
    def installed_requirements(
        requirement_sets: tuple[Requirements, ...],
    ) -> Requirements | None:
        """The set of packages to use, of the sets that can do something.

        Parameters
        ----------
        requirement_sets : tuple of tuples of Requirement classes
            E.g. ``preview_requirements``, most preferred first.

        Returns
        -------
        tuple of Requirement classes, or None
            The first set whose packages are all installed; None if there is
            none; empty if there are no sets.
        """
        if not requirement_sets:
            return ()
        for requirements in requirement_sets:
            if all(r().is_installed() for r in requirements):
                return requirements
        return None

    def can_query(self) -> bool:
        """Whether the data browser can query this format.

        Returns
        -------
        bool
            True if it has ``query_requirements``, one set of them installed.
        """
        return bool(self.query_requirements) and (
            self.installed_requirements(self.query_requirements) is not None
        )

    def install_hint(self) -> list[Preview]:
        """A preview telling the user what to install to see this format.

        Returns
        -------
        list of Preview
            An ``InstallPreview`` with, per set of ``preview_requirements``,
            the packages missing.
        """
        options = [
            [r.package for r in requirements if not r().is_installed()]
            for requirements in self.preview_requirements
        ]
        return [InstallPreview(format=self.label, options=options)]

    def recipes(self, target: Target) -> list[Recipe]:
        """The ways to load a file or folder in a notebook ("Python code").

        Parameters
        ----------
        target : Target
            The file or folder, which ``matches``.

        Returns
        -------
        list of Recipe
            One per set of ``code_requirements``, with its ``load_code``.
        """
        return [
            Recipe(
                library=requirements[0].package,
                code=self.load_code(target, requirements),
            )
            for requirements in self.code_requirements
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
