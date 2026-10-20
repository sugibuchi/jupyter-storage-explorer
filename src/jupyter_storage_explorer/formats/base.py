"""The base of formats: the ``DataFormat`` interface and ``detect``; helpers
reading a file through its fsspec filesystem (``head_text``,
``read_whole``, ...); and helpers for the code
supports generate ("Python code"): storage options fit to show, keyword
arguments for recipe templates, and URLs as libraries and Spark read them.
The predefined formats each have a module (delta.py, parquet.py, text.py,
...); handling the data is ``FormatSupport``'s (support.py)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer.filesystems.locations import LocalLocation

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.preview import PreviewLimits
    from jupyter_storage_explorer.location import Location


# --- Reading a file through its fsspec filesystem, for detection and previews ---


def name_of(path: str) -> str:
    """The last part of a path, e.g. "a.csv" of "data/a.csv"."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def child_names(children: Iterable[Mapping[str, Any]] | None) -> set[str]:
    """The names of the items of a folder's listing (fsspec's ``ls``
    entries); empty for a file's None."""
    return {name_of(c["name"]) for c in children or ()}


def file_size(fs: AbstractFileSystem, path: str) -> int | None:
    """The file's size in bytes, if its filesystem tells it."""
    return fs.info(path).get("size")


def head(fs: AbstractFileSystem, path: str, size: int) -> bytes:
    """The first ``size`` bytes of the file, without reading the rest."""
    with fs.open(path, "rb") as f:
        return f.read(size)


def head_text(fs: AbstractFileSystem, path: str, size: int) -> tuple[str, bool]:
    """The first ``size`` bytes decoded as UTF-8, and whether the file is longer.

    When the file is longer, the text is cut after its last complete line.
    """
    data = head(fs, path, size + 1)
    truncated = len(data) > size
    if truncated:
        data = data[:size]
        if (end := data.rfind(b"\n")) >= 0:
            data = data[: end + 1]
    return data.decode("utf-8-sig", errors="replace"), truncated


def read_whole(fs: AbstractFileSystem, path: str, limits: PreviewLimits) -> bytes:
    """The whole file, for formats that cannot be read in part. ValueError if
    it is larger than ``limits.max_whole_file_bytes``."""
    size = file_size(fs, path)
    if size is not None and size > limits.max_whole_file_bytes:
        limit = limits.max_whole_file_bytes // (1024 * 1024)
        raise ValueError(f"too large to preview (over {limit} MB)")
    return fs.cat_file(path)


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
    folder's listing (``children``). What detection finds and supports need
    (e.g. a Parquet dataset's partition layout) is kept by the format, by
    location: supports are given the format.

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

    def matches(
        self,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        info: Mapping[str, Any],
        children: Sequence[Mapping[str, Any]] | None,
    ) -> bool:
        """Whether a file or folder is in this format.

        Called on every click, so it must be cheap: look at the name, or the
        folder's listing (``children``), not at the contents.

        Parameters
        ----------
        location : Location
            Where it is: what the format keeps what it finds by (e.g. a
            dataset's layout), for the supports, which get the location.
        fs : AbstractFileSystem
            The filesystem it is on, to read more if needed.
        path : str
            Its path in ``fs``.
        info : mapping
            fsspec's info of it (``fs.info(path)``).
        children : sequence of mapping or None
            A folder's listing (fsspec's ``ls(path, detail=True)`` entries);
            None for a file.

        Returns
        -------
        bool
            By default: a file whose name ends with one of ``extensions``.
        """
        return children is None and name_of(path).lower().endswith(self.extensions)


def matching_formats(
    location: Location,
    fs: AbstractFileSystem,
    path: str,
    info: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]] | None,
    *,
    formats: Iterable[DataFormat],
) -> list[DataFormat]:
    """All ``formats`` that match the item (see ``DataFormat.matches``),
    highest priority first (ties keep their order)."""
    found = (f for f in formats if f.matches(location, fs, path, info, children))
    return sorted(found, key=lambda f: -f.priority)


def detect(
    location: Location,
    fs: AbstractFileSystem,
    path: str,
    info: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]] | None,
    *,
    formats: Iterable[DataFormat],
) -> DataFormat | None:
    """The highest-priority of ``formats`` that matches the item (see
    ``DataFormat.matches``), if any. On a tie, the format listed first wins."""
    best = None
    for fmt in formats:
        if not fmt.matches(location, fs, path, info, children):
            continue
        if best is None or fmt.priority > best.priority:
            best = fmt
    return best


# Storage options whose names look like credentials are left out of generated
# snippets, since snippets get copied, shared and saved in notebooks.
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


def snippet_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    """Storage options fit to put in generated code; empty for None.

    Leaves out options that look like credentials, and ones whose values are
    objects rather than plain data (e.g. the filesystem a DirFileSystem wraps).
    """
    out: dict[str, Any] = {}
    for key, value in (options or {}).items():
        if _SECRET_OPTION.search(key):
            continue
        if isinstance(value, Mapping):
            # Filtered key by key, keeping e.g. client_kwargs' endpoint_url.
            out[key] = snippet_options(value)
        elif _is_plain(value):
            out[key] = value
    return out


def format_kwargs(**kwargs: Any) -> str:
    """Python source for keyword arguments following others in a call, each
    after ", "; those that are None are left out, so it may be empty. For the
    ``{kwargs}`` of load code templates, e.g. ``"df = pl.read_csv({url}{kwargs})"``.

    >>> format_kwargs(sep=";", storage_options=None)
    ", sep=';'"
    """
    return "".join(f", {k}={v!r}" for k, v in kwargs.items() if v is not None)


# Spark (Hadoop) names for storage URLs: TLS "abfss" for Azure, as Spark
# expects it (storage accounts usually require secure transfer); "s3a", the
# S3 connector of open-source Hadoop (Databricks and EMR accept it too).
_SPARK_SCHEMES = {"abfs": "abfss", "az": "abfss", "s3": "s3a"}


def spark_url(url: str) -> str:
    """``url`` as Spark reads it, e.g. "abfss://c@a.dfs.core.windows.net/x" for
    "abfs://c@a.dfs.core.windows.net/x" or "s3a://bucket/x" for "s3://bucket/x".

    Other URLs and local paths are unchanged.
    """
    scheme, sep, rest = url.partition("://")
    return (
        f"{_SPARK_SCHEMES[scheme]}://{rest}"
        if sep and scheme in _SPARK_SCHEMES
        else url
    )


def library_url(location: Location) -> str:
    """Where most libraries read ``location`` (polars, pandas, DuckDB, ...):
    its URL, but a local file's plain path, which they all take (not all of
    them read ``file://`` URLs). Spark reads ``spark_url(location.url)``."""
    return location.path if isinstance(location, LocalLocation) else location.url
