"""The base of formats: the ``DataFormat`` interface, and ``ItemContext``,
the item formats and supports are given, with what they read of it (its
beginning, all of it, its children's names, its URL as libraries read it).
``detect`` and ``matching_formats`` are the explorer's. The predefined
formats each have a module (delta.py, parquet.py, text.py, ...); handling
the data is ``FormatSupport``'s (support.py)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.filesystems.locations import LocalLocation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.view import ViewLimits
    from jupyter_storage_explorer.location import Location


@dataclass(frozen=True, kw_only=True)
class ItemContext:
    """A file or folder, as formats (``DataFormat.matches``) and supports
    (``FormatSupport.view``, ``recipe``) are given it, and how they read it.

    One object rather than parameters, so that what they are given can grow
    without changing their signatures.

    Parameters
    ----------
    location : Location
        Where it is, independently of fsspec: what formats keep what they
        find by (e.g. a Parquet dataset's layout); libraries doing their own
        I/O read ``library_url``.
    fs : AbstractFileSystem
        The explorer's filesystem it is on, with its credentials, which
        ``head``, ``head_text`` and ``read_whole`` read it through.
    path : str
        Its path in ``fs``.
    info : mapping
        fsspec's info of it (``fs.info(path)``).
    children : sequence of mapping or None
        A folder's listing (fsspec's ``ls(path, detail=True)`` entries); None
        for a file.

    Attributes
    ----------
    is_dir : bool
        Whether it is a folder (``children`` is not None).
    name : str
        The last part of its path, e.g. "a.csv".
    child_names : set of str
        The names of a folder's items; empty for a file.
    size : int or None
        A file's size in bytes, if its filesystem tells it (from ``info``).
    library_url : str
        Where most libraries read it (polars, pandas, DuckDB, ...): its
        location's URL, but a local file's plain path, which they all take
        (not all of them read ``file://`` URLs). Spark reads its own
        spelling of ``location.url`` (``supports.pyspark.spark_url``).
    """

    location: Location
    fs: AbstractFileSystem
    path: str
    info: Mapping[str, Any]
    children: Sequence[Mapping[str, Any]] | None

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def name(self) -> str:
        return _paths.basename(self.path)

    @property
    def child_names(self) -> set[str]:
        return {_paths.basename(c["name"]) for c in self.children or ()}

    @property
    def size(self) -> int | None:
        return self.info.get("size")

    @property
    def library_url(self) -> str:
        location = self.location
        return location.path if isinstance(location, LocalLocation) else location.url

    def head(self, size: int) -> bytes:
        """The first ``size`` bytes of the file, without reading the rest."""
        with self.fs.open(self.path, "rb") as f:
            return f.read(size)

    def head_text(self, size: int) -> tuple[str, bool]:
        """The first ``size`` bytes decoded as UTF-8, and whether the file is
        longer.

        When the file is longer, the text is cut after its last complete line.
        """
        data = self.head(size + 1)
        truncated = len(data) > size
        if truncated:
            data = data[:size]
            if (end := data.rfind(b"\n")) >= 0:
                data = data[: end + 1]
        return data.decode("utf-8-sig", errors="replace"), truncated

    def read_whole(self, limits: ViewLimits) -> bytes:
        """The whole file, for formats that cannot be read in part.
        ValueError if it is larger than ``limits.max_whole_file_bytes``."""
        if self.size is not None and self.size > limits.max_whole_file_bytes:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to view (over {limit} MB)")
        return self.fs.cat_file(self.path)


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


class DataFormat:
    """How to recognise one kind of file or directory.

    Subclass it for a format of your own, and give it to ``StorageExplorer``
    (``formats=[MyFormat(), *default_formats()]``), with the supports
    handling its data (``FormatSupport``: previews, the data browser, load
    code), given as ``supports``. File formats usually only set
    ``extensions``; directory formats (Delta Lake tables, Spark output,
    Hive-partitioned datasets, ...) override ``matches`` and inspect the
    folder's listing (``ctx.children``, ``ctx.child_names``). What detection
    finds and supports need (e.g. a Parquet dataset's partition layout) is
    kept by the format, by location: supports are given the format.

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
    """

    # See the class docstring.
    name: ClassVar[str]
    label: ClassVar[str]
    priority: ClassVar[int] = 0
    extensions: ClassVar[tuple[str, ...]] = ()
    file_icon: ClassVar[str | tuple[str, str] | None] = None

    def matches(self, ctx: ItemContext) -> bool:
        """Whether a file or folder is in this format.

        Called on every click, so it must be cheap: look at the name, or the
        folder's listing (``ctx.children``), not at the contents.

        Parameters
        ----------
        ctx : ItemContext
            The file or folder: its location (what the format keeps what it
            finds by, e.g. a dataset's layout, for the supports), filesystem
            and path (to read more if needed), info and listing.

        Returns
        -------
        bool
            By default: a file whose name ends with one of ``extensions``.
        """
        return not ctx.is_dir and ctx.name.lower().endswith(self.extensions)


def matching_formats(
    ctx: ItemContext, *, formats: Iterable[DataFormat]
) -> list[DataFormat]:
    """All ``formats`` that match the item (see ``DataFormat.matches``),
    highest priority first (ties keep their order)."""
    found = (f for f in formats if f.matches(ctx))
    return sorted(found, key=lambda f: -f.priority)


def detect(ctx: ItemContext, *, formats: Iterable[DataFormat]) -> DataFormat | None:
    """The highest-priority of ``formats`` that matches the item (see
    ``DataFormat.matches``), if any. On a tie, the format listed first wins."""
    best = None
    for fmt in formats:
        if not fmt.matches(ctx):
            continue
        if best is None or fmt.priority > best.priority:
            best = fmt
    return best
