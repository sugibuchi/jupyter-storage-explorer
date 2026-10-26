"""Views of a format's data: a view action returns one of these, and
the explorer shows it in the preview panel or a tab of its own: the data
browser for a ``QueryView``, and for the table chosen of a
``TableSetView``'s; the others rendered by the frontend according to their
``kind``. A ``ViewWithPrompt`` asks the user something first, and makes the
view from the answer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, get_args

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "JupyterWidgetView",
    "Leaf",
    "MarkdownView",
    "MediaView",
    "Node",
    "QueryView",
    "TableSetView",
    "TableView",
    "TextView",
    "TreeView",
    "View",
    "ViewLimits",
    "ViewWithChoice",
    "ViewWithConfirmation",
    "ViewWithInput",
    "ViewWithPrompt",
]

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
    """What a view action returns: one of the subclasses below,
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
            it is given, in the order the functions were given (e.g. a
            connection closed before its file is released). Errors are
            logged, not raised, so that they never keep the next view from
            showing, and do not stop the other functions.
        remove : bool, default False
            Stop calling ``callback`` instead.

        See Also
        --------
        close : Calls the functions.

        Examples
        --------
        In a view action, a DuckDB table closed with its connection:

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
        ``data`` holds only the first part of the item's: eager data its
        first rows (e.g. ``ViewLimits.max_memory_rows`` of them, read with
        pandas), lazy data e.g. a file's first bytes. The data browser says
        so.
    fetch : callable or None, default None
        How the data browser reads rows of lazy ``data`` from its library,
        when the library has a cheaper way than the explorer's default: as
        ``fetch(lf, offset, length)``, rows ``offset`` to ``offset + length``
        of ``lf``, a narwhals LazyFrame of the data with the browser's
        filters, sort and hidden columns applied, as a narwhals DataFrame;
        or None to leave them to the default. Called for the first rows when
        the data opens and for each page of live queries, in worker threads.
        The explorer's ``fetch_rows``, the user's, comes first.

    Examples
    --------
    Spark (3.4 and later) skips rows itself:

    >>> def spark_rows(lf, offset, length):
    ...     page = lf.to_native().offset(offset).limit(length)
    ...     return nw.from_native(page).collect()
    >>> QueryView(data=spark.read.parquet(url), fetch=spark_rows)
    """

    kind: ClassVar[str] = "query"
    data: Any
    more: bool = False
    fetch: Callable[[Any, int, int], Any] | None = None


# The icons of a TableSetView's tree (Node.icon).
NodeIcon = Literal["folder", "database", "table"]
NODE_ICONS: tuple[str, ...] = get_args(NodeIcon)


@dataclass(frozen=True, kw_only=True)
class Node:
    """A group of tables in a ``TableSetView``'s tree, e.g. a database's
    schema.

    Parameters
    ----------
    label : str
        Shown in the tree.
    children : sequence of Node, default ()
        The groups and tables (``Leaf``) in it.
    icon : {"folder", "database", "table"}, default "folder"
        Shown before the label, e.g. "database" for a database's schema.

    Raises
    ------
    ValueError
        If ``icon`` is unknown.
    """

    label: str
    children: Sequence[Node] = ()
    icon: NodeIcon = "folder"

    def __post_init__(self) -> None:
        if self.icon not in NODE_ICONS:
            known = ", ".join(f'"{icon}"' for icon in NODE_ICONS)
            raise ValueError(f"icon must be one of {known}, not {self.icon!r}")


@dataclass(frozen=True, kw_only=True)
class Leaf(Node):
    """A table of a ``TableSetView``, which its ``loader`` reads by ``id``.

    Parameters
    ----------
    label : str
        Shown in the tree or on its tab.
    id : str
        What ``loader`` is given, unique in the view (e.g. "sales.orders").
    icon : {"folder", "database", "table"}, default "table"
        Shown before the label in the tree.

    Raises
    ------
    ValueError
        If given ``children``: a table holds none. If ``icon`` is unknown.
    """

    id: str
    icon: NodeIcon = "table"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.children:
            raise ValueError(f"table {self.label!r} cannot have children")


@dataclass(frozen=True, kw_only=True)
class TableSetView(View):
    """Several tables of one item, e.g. a database's or a workbook's: the
    user chooses one, which the data browser shows as it shows a
    ``QueryView``'s data.

    Parameters
    ----------
    nodes : sequence of Node
        The tables (``Leaf``), maybe in groups (``Node``).
    loader : callable
        Reads a table, as ``loader(id)``: any dataframe narwhals supports,
        best lazy, as a ``QueryView``'s ``data``; or a ``QueryView`` of it,
        e.g. with ``more=True`` for eager data holding the first rows only
        (it is closed once the table is no longer shown). Called when the
        table is chosen, and again when the data browser reads it again. What
        it holds open (e.g. a database connection) stays readable until the
        view is closed: release it with ``on_close``.
    selector : {"tree", "tab"}, default "tree"
        How tables are chosen: in a tree beside the table, or on tabs below
        it, as a spreadsheet's sheets ("tab": ``nodes`` are all tables, with
        no groups).

    Raises
    ------
    ValueError
        If ``selector`` is unknown, "tab" with groups, no table is given, or
        two tables have one ``id``.

    Examples
    --------
    In a view action, a workbook's sheets:

    >>> sheets = pl.read_excel(path, sheet_id=0)  # {name: DataFrame}
    >>> TableSetView(
    ...     nodes=[Leaf(label=name, id=name) for name in sheets],
    ...     loader=sheets.__getitem__,
    ...     selector="tab",
    ... )

    A local database's schemas and tables, read by SQL (``con.table`` fails
    for a view named with its schema), the connection closed with the view:

    >>> con = duckdb.connect(path, read_only=True)
    >>> sql = {"sales.orders": 'select * from "sales"."orders"'}
    >>> orders = Leaf(label="orders", id="sales.orders")
    >>> view = TableSetView(
    ...     nodes=[Node(label="sales", children=[orders], icon="database")],
    ...     loader=lambda id: con.sql(sql[id]),
    ... )
    >>> view.on_close(lambda view: con.close())
    """

    kind: ClassVar[str] = "table_set"
    nodes: Sequence[Node]
    loader: Callable[[str], Any]
    selector: Literal["tree", "tab"] = "tree"

    def __post_init__(self) -> None:
        if self.selector not in ("tree", "tab"):
            raise ValueError(f'selector must be "tree" or "tab", not {self.selector!r}')
        if self.selector == "tab" and not all(isinstance(n, Leaf) for n in self.nodes):
            raise ValueError('selector "tab" takes tables (Leaf) only, with no groups')
        ids = [leaf.id for leaf in self.leaves()]
        if not ids:
            raise ValueError("a table set needs at least one table (Leaf)")
        if len(set(ids)) < len(ids):
            twice = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"tables' ids must be unique: {', '.join(twice)}")

    def leaves(self) -> list[Leaf]:
        """The tables, in the order the tree shows them."""

        def walk(nodes: Sequence[Node]) -> list[Leaf]:
            return [
                leaf
                for node in nodes
                for leaf in ([node] if isinstance(node, Leaf) else walk(node.children))
            ]

        return walk(self.nodes)


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


@dataclass(frozen=True, kw_only=True)
class JupyterWidgetView(View):
    """A Jupyter widget, shown as it is: an ipywidgets control, a chart's
    or a map's widget, or an anywidget of your own.

    The page renders it with its widget manager, as a notebook's output
    would be. The view owns the widget: closing the view closes it, so
    that the kernel lets it go. Return a new widget each time, never one
    shown elsewhere.

    Parameters
    ----------
    widget : ipywidgets.DOMWidget
        The widget shown.

    Raises
    ------
    TypeError
        If ``widget`` is no ``ipywidgets.DOMWidget``.

    Examples
    --------
    In a view action:

    >>> import ipywidgets
    >>> return JupyterWidgetView(widget=ipywidgets.HTML(f"<b>{name}</b>"))
    """

    kind: ClassVar[str] = "widget"
    widget: Any

    def __post_init__(self) -> None:
        if not is_jupyter_widget(self.widget):
            raise TypeError(
                f"a JupyterWidgetView shows an ipywidgets.DOMWidget, not "
                f"{type(self.widget).__name__}"
            )
        self.on_close(lambda view: view.widget.close())


def is_jupyter_widget(value: Any) -> bool:
    """Whether ``value`` is a widget the page can render: an
    ``ipywidgets.DOMWidget``, anywidgets included."""
    import ipywidgets  # noqa: PLC0415  # imported once a widget is shown

    return isinstance(value, ipywidgets.DOMWidget)


@dataclass(frozen=True, kw_only=True)
class ViewWithPrompt(View):
    """A question to the user, whose answer makes the view: one of the
    subclasses below, e.g. before reading a whole large file.

    The explorer shows ``message`` where the view would be, with ``button``
    and Cancel (a choice, Cancel only ``with_cancel``). Once the user
    answers, it calls ``answer`` in a worker thread, as it calls ``view()``,
    and shows the view it returns: maybe another prompt. Cancel shows
    nothing.

    The answers are kept with the view: when the data browser reads the data
    again, the prompts the action returns are answered the same way,
    without asking.

    The prompt is closed with the view its answer made, or when cancelled,
    so the functions given to its ``on_close`` may release what that view
    reads.

    Parameters
    ----------
    message : str
        The question, e.g. "Polars reads the whole file (586 MB) into
        memory."
    button : str, default "View"
        The button answering it.
    """

    message: str
    button: str = "View"

    def answer(self, value: Any = None) -> View:
        """The view of the user's answer.

        Parameters
        ----------
        value : Any
            What the user answered: nothing for a confirmation, the label
            chosen for a choice, the text entered for an input.

        Returns
        -------
        View
            What its function made of the answer.

        Raises
        ------
        TypeError
            If the function returns no ``View``.
        ValueError
            If ``value`` is no possible answer.
        """
        view = self._make(value)
        if not isinstance(view, View):
            raise TypeError(f"the prompt's function returned no View: {view!r}")
        return view

    def _make(self, value: Any) -> View:
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class ViewWithConfirmation(ViewWithPrompt):
    """A confirmation: the view is made only once the user clicks
    ``button``.

    Parameters
    ----------
    message : str
        What viewing does, e.g. "Polars reads the whole file (586 MB) into
        memory."
    factory : callable
        Makes the view, as ``factory()``.
    button : str, default "View"

    Examples
    --------
    In a view action:

    >>> return ViewWithConfirmation(
    ...     message=f"This reads the whole file ({size_mb} MB).",
    ...     factory=lambda: QueryView(data=read_whole()),
    ... )
    """

    kind: ClassVar[str] = "confirmation"
    factory: Callable[[], View]

    def _make(self, value: Any) -> View:
        return self.factory()


@dataclass(frozen=True, kw_only=True)
class ViewWithChoice(ViewWithPrompt):
    """A choice: the view is made of the value of the label the user
    chooses.

    Parameters
    ----------
    message : str
        What is chosen, e.g. "Polars cannot read this storage itself."
    choices : mapping of str to Any
        The labels shown, in order, and the values ``factory`` is given.
    factory : callable
        Makes the view, as ``factory(value)``.
    style : {"radio", "dropdown", "button"}, default "radio"
        Radio buttons, for a few choices, or a dropdown menu, each with
        ``button``; or a button of each label, which answers at once, for two
        or three short choices.
    default : str or None, default None
        The label chosen at first; by default the first. With "button", the
        primary button.
    button : str, default "View"
        Not shown with "button".
    with_cancel : bool, default False
        Also a Cancel button, which shows nothing: for choices of how to
        read, where not reading is a choice too.

    Raises
    ------
    ValueError
        If there are no choices, ``style`` is unknown, or ``default`` is no
        label.

    Examples
    --------
    >>> return ViewWithChoice(
    ...     message="The file is 586 MB.",
    ...     choices={"The whole file": None, "Its first 10 MB": 10 * 2**20},
    ...     factory=lambda size: QueryView(data=read(size)),
    ...     style="button",
    ...     with_cancel=True,
    ... )
    """

    kind: ClassVar[str] = "choice"
    choices: Mapping[str, Any]
    factory: Callable[[Any], View]
    style: Literal["radio", "dropdown", "button"] = "radio"
    default: str | None = None
    with_cancel: bool = False

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError("a choice needs at least one label")
        if self.style not in ("radio", "dropdown", "button"):
            raise ValueError(
                f'style must be "radio", "dropdown" or "button", not {self.style!r}'
            )
        if self.default is not None and self.default not in self.choices:
            raise ValueError(f"default {self.default!r} is not one of the labels")

    def _make(self, value: Any) -> View:
        if value not in self.choices:
            raise ValueError(f"{value!r} is not one of the choices")
        return self.factory(self.choices[value])


@dataclass(frozen=True, kw_only=True)
class ViewWithInput(ViewWithPrompt):
    """A text to enter: the view is made of what the user enters.

    Parameters
    ----------
    message : str
        What to enter, e.g. "The workbook's password".
    factory : callable
        Makes the view, as ``factory(text)``.
    value : str, default ""
        The text at first.
    placeholder : str, default ""
        Shown in the empty field.
    button : str, default "View"
    """

    kind: ClassVar[str] = "input"
    factory: Callable[[str], View]
    value: str = ""
    placeholder: str = ""

    def _make(self, value: Any) -> View:
        return self.factory("" if value is None else str(value))
