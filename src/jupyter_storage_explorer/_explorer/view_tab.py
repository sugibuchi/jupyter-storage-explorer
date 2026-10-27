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
    need ("vendor"), as the explorer's does.

    It also shows a prompt (``ViewWithPrompt``) before the view: the user's
    answer ("answer") goes to ``on_answer``, and the widget then shows what
    the explorer gives it (``_show``): that the view loads, its error, or
    another prompt. The view itself replaces the widget in the tab."""

    _esm = _static.esm("view_tab")
    _css = _static.css("view_tab")

    # The view, as the frontend renders it: {"kind", ...its fields}.
    _view = traitlets.Dict().tag(sync=True)
    # The tab's title bar: the item's name, and its format's label.
    _title = traitlets.Unicode().tag(sync=True)
    _label = traitlets.Unicode().tag(sync=True)

    def __init__(
        self,
        view: dict[str, Any],
        *,
        title: str,
        label: str,
        on_close: Callable[[], object] | None = None,
        on_answer: Callable[[dict[str, Any]], object] | None = None,
    ) -> None:
        super().__init__(_view=view, _title=title, _label=label)
        # The view's own close, called when the tab closes the widget.
        self._on_close = on_close
        # Given the answer to the prompt shown, if one is.
        self._on_answer = on_answer
        self.on_msg(self._on_custom_msg)

    def _show(
        self,
        view: dict[str, Any],
        *,
        on_close: Callable[[], object] | None = None,
        on_answer: Callable[[dict[str, Any]], object] | None = None,
    ) -> None:
        """Show another section instead, with its own ``on_close`` and
        ``on_answer``. The previous ``on_close`` is not called: what it
        closed goes on in what replaces it, e.g. a prompt in the view of its
        answer."""
        self._on_close = on_close
        self._on_answer = on_answer
        self._view = view

    def close(self) -> None:
        self._release()
        super().close()

    def _release(self, *, now: bool = False) -> None:
        """Close the view, without closing the widget: when it closes, and at
        the kernel's exit (``now``, which changes nothing here: no request
        reads the view)."""
        on_close, self._on_close = getattr(self, "_on_close", None), None
        if on_close is not None:
            on_close()

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], buffers: Any
    ) -> None:
        if content.get("type") == "vendor":
            reply = _static.vendor_source(str(content.get("name")))
            self.send({"type": "reply", "rid": content.get("rid"), **reply})
        elif content.get("type") == "answer" and self._on_answer is not None:
            self._on_answer(content)
