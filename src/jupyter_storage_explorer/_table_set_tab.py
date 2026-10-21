"""A ``TableSetView`` in a tab of its own ("View in a new tab"): its tables
in a tree or on tabs, and the data browser on the one chosen, as the preview
panel shows them (``createTableSetPanel`` in static/query.js)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static
from jupyter_storage_explorer._query.table_set import SEPARATOR

if TYPE_CHECKING:
    from jupyter_storage_explorer._query.table_set import TableSet


class TableSetTab(anywidget.AnyWidget):
    """The tables of a ``TableSet`` under a title bar, filling the tab; closing
    it closes the table's query and the view."""

    _esm = _static.esm("table_set_tab")
    _css = _static.css("table_set_tab")

    # The tab's title bar: the item's name, and its format's label.
    title = traitlets.Unicode().tag(sync=True)
    label = traitlets.Unicode().tag(sync=True)
    # TableSet.opening(): the tables, and the one chosen at first.
    tables = traitlets.Dict().tag(sync=True)

    def __init__(self, tables: TableSet, *, title: str, label: str) -> None:
        super().__init__(title=title, label=label, tables=tables.opening())
        self._tables: TableSet | None = tables
        self.on_msg(self._on_custom_msg)

    def close(self) -> None:
        self._release()
        super().close()

    def _release(self) -> None:
        """Close the tables, without closing the widget: when it closes, and
        at the kernel's exit."""
        tables, self._tables = getattr(self, "_tables", None), None
        if tables is not None:
            tables.close()

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the panel's requests: "table_set_open", and the data
        browser's on the table chosen, whose "path" names it (see
        ``table_set.query_path``)."""
        tables = self._tables
        if tables is None or "rid" not in content:
            return
        if content.get("type") == "table_set_open":
            reply = tables.choose(content)
        else:
            _, _, table = str(content.get("path", "")).partition(SEPARATOR)
            reply = tables.handle(content, table)
        self.send({"type": "reply", "rid": content["rid"], **reply})
