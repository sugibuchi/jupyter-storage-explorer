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
    """

    kind: ClassVar[str]
    title: str = ""
    note: str = ""
    # The functions given to on_close, and whether close() has called them.
    # Frozen, as views are values; what is done once they are shown is not.
    _close_callbacks: list[Callable[[View], Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    def on_close(
        self, callback: Callable[[View], Any], *, remove: bool = False
    ) -> None:
        """Call a function when the view is closed (``close()``), to release
        what it holds, e.g. a database connection or a temporary copy of the
        file.

        The data of a ``QueryView`` must stay readable until then.

        Parameters
        ----------
        callback : callable
            Called with the view, as ``callback(view)``, once, however often
            it is given. Errors are logged, not raised, so that they never
            keep the next view from showing, and do not stop the other
            functions.
        remove : bool, default False
            Stop calling ``callback`` instead.

        See Also
        --------
        close : Calls the functions.

        Examples
        --------
        In a support's ``view()``, a DuckDB table closed with its connection:

        >>> con = duckdb.connect(path, read_only=True)
        >>> view = QueryView(data=con.table("orders"))
        >>> view.on_close(lambda view: con.close())
        """
        if remove:
            if callback in self._close_callbacks:
                self._close_callbacks.remove(callback)
        elif callback not in self._close_callbacks:
            self._close_callbacks.append(callback)

    def close(self) -> None:
        """Call the ``on_close`` functions, the first time only.

        The explorer calls it once it stops showing the view: another item
        previewed, the preview panel or the view's tab closed, another storage
        shown, the explorer closed, the data browser's data read again (once
        the new view is open), or the kernel exiting (shut down or
        restarted; not killed).
        """
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        for callback in list(self._close_callbacks):
            try:
                callback(self)
            except Exception:
                log.exception("Closing a %s view failed", self.kind)


@dataclass(frozen=True, kw_only=True)
class QueryView(View):
    """Data to query in the data browser: filters, sort, columns, pages.

    ``data`` is any dataframe narwhals supports, best lazy (e.g. a polars
    LazyFrame or a Spark DataFrame), so the browser reads only the rows it
    shows; eager ones are queried in memory.

    Parameters
    ----------
    data : dataframe
        The data.
    more : bool, default False
        ``data`` is eager and holds only the first rows of the item's (e.g.
        ``ViewLimits.max_memory_rows`` of them, read with pandas): the data
        browser says so.
    """

    kind: ClassVar[str] = "query"
    data: Any
    more: bool = False


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
    """A table of rows already read, e.g. the first rows of a file.

    The explorer notes under it how many rows it shows, from ``more``,
    ``total`` and ``unit`` (e.g. "First 100 of 1,234 rows"), before
    ``note`` (e.g. "other sheets: ...").
    """

    kind: ClassVar[str] = "table"
    columns: list[str]
    rows: list[list[Any]]
    dtypes: list[str] | None = None
    # Whether the data has more rows than ``rows``, and how many in all if
    # known (None if not).
    more: bool = False
    total: int | None = None
    # What a row is, plural, e.g. "records" for JSON Lines.
    unit: str = "rows"


@dataclass(frozen=True, kw_only=True)
class TreeView(View):
    """Collapsible view of JSON-like data."""

    kind: ClassVar[str] = "tree"
    value: Any


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
