"""The base of formats: the ``DataFormat`` interface, which looks at the
item it is given, an ``ItemContext`` (the root ``base.py``). ``detect`` and
``matching_formats`` are the explorer's. The predefined formats each have a
module (delta.py, parquet.py, text.py, ...); what is done with the data is
actions' (the ``actions`` package)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jupyter_storage_explorer.base import ItemContext


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

    Subclass it for a format of your own, and give ``StorageExplorer`` the
    actions of its data as ``actions``: views and code, whose ``format`` it
    is. Explorers detect the formats of their actions, one object of each.

    File formats usually only set ``extensions``. Directory formats, e.g.
    Delta Lake tables, Spark output or Hive-partitioned datasets, override
    ``matches`` and inspect the folder's listing (``ctx.children``,
    ``ctx.child_names``). What detection finds and actions need, e.g. a
    Parquet dataset's partition layout, is kept by the format, by location:
    actions are given the format.

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
    sniff_bytes : int, default 0
        Above 0, how many of a file's first bytes ``sniff`` needs: files this
        format ``matches`` are then confirmed by their contents (e.g. ".db",
        both SQLite's and DuckDB's), always, whichever other formats are
        installed. Listings never read files, so such files show no format
        there until they are clicked. Folders are never sniffed.
    """

    # See the class docstring.
    name: ClassVar[str]
    label: ClassVar[str]
    priority: ClassVar[int] = 0
    extensions: ClassVar[tuple[str, ...]] = ()
    file_icon: ClassVar[str | tuple[str, str] | None] = None
    sniff_bytes: ClassVar[int] = 0

    def matches(self, ctx: ItemContext) -> bool:
        """Whether a file or folder is in this format.

        Called for every file of a listing, so it must be cheap: look at the
        name, or the folder's listing (``ctx.children``), never at the
        contents (that is ``sniff``'s).

        Parameters
        ----------
        ctx : ItemContext
            The file or folder: its location (what the format keeps what it
            finds by, e.g. a dataset's layout, for the actions), filesystem
            and path (to read more if needed), info and listing.

        Returns
        -------
        bool
            By default: a file whose name ends with one of ``extensions``.
        """
        return not ctx.is_dir and ctx.name.lower().endswith(self.extensions)

    def sniff(self, ctx: ItemContext, head: bytes) -> bool:
        """Whether a file this format ``matches`` is in it, by its contents:
        its signature, e.g. ``head.startswith(b"SQLite format 3\\x00")``.

        Called only if ``sniff_bytes`` is above 0, once the item was clicked,
        with the file's first bytes read once for every format sniffing it.

        Parameters
        ----------
        ctx : ItemContext
            The file, as ``matches`` was given it.
        head : bytes
            Its first ``sniff_bytes`` bytes (the most any format matching it
            asked for); fewer if the file is shorter.

        Returns
        -------
        bool
            By default True.
        """
        return True


def _sniffs(fmt: DataFormat, ctx: ItemContext) -> bool:
    return fmt.sniff_bytes > 0 and not ctx.is_dir


def _confirmed(ctx: ItemContext, found: list[DataFormat]) -> list[DataFormat]:
    """``found`` without the formats whose ``sniff`` refuses the file's first
    bytes, read once for all of them. A file that cannot be read confirms
    none: an unread signature is no match."""
    sniffing = [f for f in found if _sniffs(f, ctx)]
    if not sniffing:
        return found
    try:
        head = ctx.head(max(f.sniff_bytes for f in sniffing))
    except Exception:
        head = None
    return [
        f
        for f in found
        if not _sniffs(f, ctx) or (head is not None and f.sniff(ctx, head))
    ]


def matching_formats(
    ctx: ItemContext, *, formats: Iterable[DataFormat]
) -> list[DataFormat]:
    """All ``formats`` that match the item (see ``DataFormat.matches``),
    confirmed by its contents where they sniff (``DataFormat.sniff``),
    highest priority first (ties keep their order)."""
    found = _confirmed(ctx, [f for f in formats if f.matches(ctx)])
    return sorted(found, key=lambda f: -f.priority)


def detect(
    ctx: ItemContext, *, formats: Iterable[DataFormat], sniff: bool = True
) -> DataFormat | None:
    """The highest-priority of ``formats`` that matches the item (see
    ``DataFormat.matches``), if any. On a tie, the format listed first wins.

    Formats that sniff are confirmed by the item's contents. Without
    ``sniff`` (listings, which never read files), an item one of them
    matches is undecided: None, rather than a guess its contents may
    contradict."""
    found = [f for f in formats if f.matches(ctx)]
    if not sniff and any(_sniffs(f, ctx) for f in found):
        return None
    best = None
    for fmt in _confirmed(ctx, found):
        if best is None or fmt.priority > best.priority:
            best = fmt
    return best
