"""A ``TableSetView`` in a tab of its own ("View in a new tab"): its tables
in a tree or on tabs, and the data browser on the one chosen, as the preview
panel shows them (``createTableSetPanel`` in static/query.js)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static
from jupyter_storage_explorer._jobs.loader import Loader

if TYPE_CHECKING:
    from jupyter_storage_explorer._query.table_set import TableSet


class TableSetTab(anywidget.AnyWidget):
    """The tables of a ``TableSet`` under a title bar, filling the tab; closing
    it closes the table's query and the view."""

    _esm = _static.esm("table_set_tab")
    _css = _static.css("table_set_tab")

    # The tab's title bar: the item's name, and its format's label.
    _title = traitlets.Unicode().tag(sync=True)
    _label = traitlets.Unicode().tag(sync=True)
    # TableSet.opening(): the tables, and the one chosen at first.
    _tables = traitlets.Dict().tag(sync=True)

    def __init__(self, tables: TableSet, *, title: str, label: str) -> None:
        super().__init__(_title=title, _label=label, _tables=tables.opening())
        self._table_set: TableSet | None = tables
        self._loader = Loader()
        self.on_msg(self._on_custom_msg)

    def close(self) -> None:
        self._release()
        super().close()

    def _release(self, *, now: bool = False) -> None:
        """Close the tables, without closing the widget: when it closes,
        after the requests still reading them, and at the kernel's exit
        (``now``)."""
        tables, self._table_set = getattr(self, "_table_set", None), None
        if tables is None:
            return
        if now:
            tables.close()
        else:
            self._loader.close_in_lane(tables, tables.close)

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the panel's requests: "table_set_open", and the data
        browser's on the table chosen, whose "path" names it (see
        ``table_set.query_path``). In a worker thread, one at a time, as
        the preview panel's (see ``PreviewsMixin._answer_query``)."""
        tables = self._table_set
        if tables is None or "rid" not in content:
            return

        def reply(answer: dict[str, Any]) -> None:
            self.send({"type": "reply", "rid": content["rid"], **answer})

        self._loader.answer(tables, lambda: tables.answer(content), reply)
