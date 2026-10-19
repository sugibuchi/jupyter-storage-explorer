"""How to detect each kind of data: the ``DataFormat`` interface, and the
``Target`` it looks at (the predefined formats each have a module: delta.py,
parquet.py, text.py, ...). Handling the data is ``FormatSupport``'s
(support.py)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.preview import PreviewLimits
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

    # The packages the code needs: the library it loads with first (its
    # support's ``use``, which names the recipe, e.g. "Load with polars"),
    # then the others (``additional_requirements``); empty for Python alone.
    requirements: Requirements
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


class DataFormat:
    """How to recognise one kind of file or directory.

    Subclass it for a format of your own, and give it to ``StorageExplorer``
    (``formats=[MyFormat(), *default_formats()]``), with the supports
    handling its data (``FormatSupport``: previews, the data browser, load
    code), given as ``supports``. File formats usually only set
    ``extensions``; directory formats (Delta Lake tables, Spark output,
    Hive-partitioned datasets, ...) override ``matches`` and inspect
    ``target.children``. What detection finds and supports need (e.g. a
    Parquet dataset's partition layout) is kept by the format: supports are
    given it.

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
