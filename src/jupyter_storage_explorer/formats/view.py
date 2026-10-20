"""Views of a format's data: ``FormatSupport.view`` returns one of these, and
the explorer shows it in the preview panel or a tab of its own: the data
browser for a ``QueryView``, the others rendered by the frontend according
to their ``kind``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ViewLimits:
    """How much a view reads and shows, wherever it is shown: the preview
    panel or a tab of its own.

    Attributes
    ----------
    max_bytes : int, default 64 KiB
        Views of a file's beginning (text, JSON, CSV read by pandas, ...)
        read at most this many bytes.
    max_display_rows : int, default 100
        Rows of a table view (``TableView``); also the data browser's page
        size.
    max_whole_file_bytes : int, default 10 MiB
        Largest file read whole, e.g. images (sent to the browser) and Excel
        workbooks.
    max_live_rows : int, default 5000
        The data browser (``QueryView``): in "auto" mode, data of at most
        this many rows is read once and kept in memory.
    max_memory_rows : int, default 100_000
        The data browser: the most rows read into memory, and the most rows
        a live query gives.
    """

    max_bytes: int = 64 * 1024
    max_display_rows: int = 100
    max_whole_file_bytes: int = 10 * 1024 * 1024
    max_live_rows: int = 5000
    max_memory_rows: int = 100_000


@dataclass(frozen=True, kw_only=True)
class View:
    """What a support's ``view()`` returns: one of the subclasses below,
    which the explorer shows by their ``kind``.

    Parameters
    ----------
    title : str, default ""
        Shown above the view.
    note : str, default ""
        Shown under the view, e.g. "First 100 rows of 1,234,567".
    on_close : callable or None, default None
        Called without arguments by ``close()``, once the explorer no longer
        shows the view, to release what it holds (e.g. a database connection,
        a temporary copy of the file). The data of a ``QueryView`` must stay
        readable until then.

    Examples
    --------
    >>> con = duckdb.connect(path, read_only=True)
    >>> QueryView(data=con.table("orders"), on_close=con.close)
    """

    kind: ClassVar[str]
    title: str = ""
    note: str = ""
    on_close: Callable[[], object] | None = field(
        default=None, repr=False, compare=False
    )
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    def close(self) -> None:
        """Call ``on_close``, the first time only.

        The explorer calls it once it stops showing the view: another item
        previewed, the preview panel or the view's tab closed, another storage
        shown, the explorer closed, or the data browser's data read again
        (once the new view is open). An error of ``on_close`` is logged, not
        raised, so that it never keeps the next view from showing.
        """
        if self._closed:
            return
        # Frozen, as views are values; whether it was closed is not one.
        object.__setattr__(self, "_closed", True)
        if self.on_close is None:
            return
        try:
            self.on_close()
        except Exception:
            log.exception("Closing a %s view failed", self.kind)


@dataclass(frozen=True, kw_only=True)
class QueryView(View):
    """Data to query in the data browser: filters, sort, columns, pages.

    ``data`` is any dataframe narwhals supports, best lazy (e.g. a polars
    LazyFrame or a Spark DataFrame), so the browser reads only the rows it
    shows; eager ones are queried in memory.
    """

    kind: ClassVar[str] = "query"
    data: Any


@dataclass(frozen=True, kw_only=True)
class TextView(View):
    kind: ClassVar[str] = "text"
    text: str
    # Hint for syntax highlighting, e.g. "python", "json", "yaml".
    language: str | None = None
    # ``text`` with syntax highlighting: HTML-escaped, with tokens in
    # <span class="..."> using Pygments' short class names (k, s, c, ...).
    html: str | None = None


@dataclass(frozen=True, kw_only=True)
class MarkdownView(View):
    """Markdown source; the frontend renders it to (sanitized) HTML."""

    kind: ClassVar[str] = "markdown"
    text: str


@dataclass(frozen=True, kw_only=True)
class TableView(View):
    """A table of rows already read, e.g. the first rows of a file."""

    kind: ClassVar[str] = "table"
    columns: list[str]
    rows: list[list[Any]]
    dtypes: list[str] | None = None


@dataclass(frozen=True, kw_only=True)
class TreeView(View):
    """Collapsible view of JSON-like data."""

    kind: ClassVar[str] = "tree"
    value: Any


@dataclass(frozen=True, kw_only=True)
class InstallView(View):
    """Shown instead of a view when the packages to read the format are missing."""

    kind: ClassVar[str] = "install"
    format: str  # e.g. "Delta Lake table"
    # One per set of requirements that could view it, most preferred first:
    # the names of its packages still missing, e.g. ["polars", "deltalake"].
    options: list[list[str]]


@dataclass(frozen=True, kw_only=True)
class MediaView(View):
    """Content the browser renders natively (image, PDF, audio, video), chosen by ``mime``.

    Exactly one of ``data`` (bytes sent to the browser) or ``src`` (e.g. a
    signed URL the browser fetches itself) is set.
    """

    kind: ClassVar[str] = "media"
    mime: str
    data: bytes | None = None
    src: str | None = None
