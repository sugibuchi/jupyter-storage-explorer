"""A view of a file or folder in a tab of its own ("View in a new tab"), for
views other than the data browser's (a ``QueryView`` opens a
``DataExplorer``): text, a JSON tree, an image, a table of first rows, ...
rendered as the preview panel renders them (static/sections.js)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static

if TYPE_CHECKING:
    from collections.abc import Callable


class ViewTab(anywidget.AnyWidget):
    """A view's section (``PreviewsMixin``'s ``section``) under a title bar,
    filling the tab. Its frontend asks for the libraries Markdown views
    need ("vendor"), as the explorer's does."""

    _esm = _static.esm("view_tab")
    _css = _static.css("view_tab")

    # The view, as the frontend renders it: {"kind", ...its fields}.
    view = traitlets.Dict().tag(sync=True)
    # The tab's title bar: the item's name, and its format's label.
    title = traitlets.Unicode().tag(sync=True)
    label = traitlets.Unicode().tag(sync=True)

    def __init__(
        self,
        view: dict[str, Any],
        *,
        title: str,
        label: str,
        on_close: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(view=view, title=title, label=label)
        # The view's own close, called when the tab closes the widget.
        self._on_close = on_close
        self.on_msg(self._on_custom_msg)

    def close(self) -> None:
        on_close, self._on_close = self._on_close, None
        if on_close is not None:
            on_close()
        super().close()

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], buffers: Any
    ) -> None:
        if content.get("type") == "vendor":
            reply = _static.vendor_source(str(content.get("name")))
            self.send({"type": "reply", "rid": content.get("rid"), **reply})
