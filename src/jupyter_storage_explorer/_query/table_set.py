"""A ``TableSetView`` open in the data browser (``TableSet``): its tables, the
one chosen and its ``DataQuery``; for the preview panel and view tabs alike."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer.views import Leaf, TableSetView

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from jupyter_storage_explorer._query.data_query import DataQuery
    from jupyter_storage_explorer.views import Node, View

# Between the item's path and a table's id in the data browser's requests'
# "path" (see query_path): neither holds it.
SEPARATOR = "\x00"


def query_path(path: str, table: str) -> str:
    """The "path" the data browser's requests carry for ``table`` of the
    table set at ``path``: a reply to the panel of a table no longer shown is
    then refused, not given another table's rows (nor its settings
    remembered for another table)."""
    return f"{path}{SEPARATOR}{table}"


def _nodes_json(nodes: Sequence[Node]) -> list[dict[str, Any]]:
    """The tree for the frontend: {"label", "icon", "id"} for tables,
    {"label", "icon", "children"} for groups."""
    return [
        {"label": node.label, "icon": node.icon, "id": node.id}
        if isinstance(node, Leaf)
        else {
            "label": node.label,
            "icon": node.icon,
            "children": _nodes_json(node.children),
        }
        for node in nodes
    ]


class TableSet:
    """A ``TableSetView`` in the data browser: the table chosen (the first at
    first), queried by a ``DataQuery`` that ``make_query(id, load)`` makes,
    reading it with ``load(again)`` (``_load``). One table is open at a time:
    choosing another closes the previous one's query. A reload (``again``)
    reads the table from a new view, ``view_again()``'s, which replaces the
    view (closed). ``close()`` closes the query, then the view."""

    def __init__(
        self,
        view: TableSetView,
        make_query: Callable[[str, Callable[[bool], Any]], DataQuery],
        view_again: Callable[[], View] | None = None,
    ) -> None:
        self.view = view
        self._make_query = make_query
        self._view_again = view_again
        self.table: str = view.leaves()[0].id
        self.query: DataQuery | None = None
        # Why the table chosen could not be read, if it could not.
        self.error = ""
        self._open(self.table)

    def _load(self, table: str, again: bool) -> Any:
        """``table``'s data, ``loader(table)``'s: from the view, or, ``again``
        (a reload), from the item viewed again, if that still holds it."""
        view = self.view
        if again and self._view_again is not None:
            view = self._view_again()
            if not isinstance(view, TableSetView):
                view.close()
                raise ValueError("the item no longer holds tables")
            if table not in {leaf.id for leaf in view.leaves()}:
                view.close()
                raise ValueError(f"the table {table!r} is no longer there")
            previous, self.view = self.view, view
            previous.close()
        return view.loader(table)

    def _open(self, table: str) -> None:
        """Query ``table`` instead of the table shown, if it can be read."""
        previous, self.query = self.query, None
        if previous is not None:
            previous.close()
        self.table = table
        try:
            self.query = self._make_query(table, lambda again: self._load(table, again))
        except Exception as exc:
            self.error = error_text(exc)
        else:
            self.error = ""

    def state(self) -> dict[str, Any]:
        """The table chosen for the frontend: {"table", "query"} (its
        ``DataQuery.opening()``) or {"table", "error"}."""
        if self.query is None:
            return {"table": self.table, "error": self.error}
        return {"table": self.table, "query": self.query.opening()}

    def opening(self) -> dict[str, Any]:
        """What the frontend needs to show the set: {"selector", "nodes"} and
        the table chosen (``state()``)."""
        return {
            "selector": self.view.selector,
            "nodes": _nodes_json(self.view.nodes),
            **self.state(),
        }

    def choose(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "table_set_open": query the table ``content["table"]``."""
        table = content.get("table")
        if table not in {leaf.id for leaf in self.view.leaves()}:
            return {"error": f"no table {table!r}"}
        self._open(table)
        return self.state()

    def query_of(self, table: str) -> DataQuery | None:
        """The query of ``table`` if it is the one shown (see ``query_path``)."""
        return self.query if table == self.table else None

    def handle(self, content: dict[str, Any], table: str) -> dict[str, Any]:
        """Answer the data browser's request on ``table`` (``DataQuery.handle``)."""
        query = self.query_of(table)
        if query is None:
            return {"error": "another table is shown; choose this one again"}
        return query.handle(content) or {}

    def close(self) -> None:
        """Close the table's query, then the view (``View.close``)."""
        query, self.query = self.query, None
        if query is not None:
            query.close()
        self.view.close()
