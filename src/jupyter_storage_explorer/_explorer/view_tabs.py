"""StorageExplorer's views in tabs of their own ("View in a new tab"),
which the launcher's JupyterLab extension shows (a mixin of the class)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._errors import error_text
from jupyter_storage_explorer._explorer.previews import (
    _LOADING,
    _Asking,
    _empty_preview,
    _not_viewed,
    action_id,
)
from jupyter_storage_explorer._explorer.table_set_tab import TableSetTab
from jupyter_storage_explorer._explorer.view_tab import ViewTab
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.table_set import TableSet
from jupyter_storage_explorer.data_explorer import DataExplorer

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer._explorer.previews import _Loaded


class ViewTabsMixin:
    """Views in tabs of their own: a ``DataExplorer`` of the data for a
    ``QueryView``, a ``TableSetTab`` for a ``TableSetView``, else a
    ``ViewTab`` of the view."""

    def _view_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "view_tab": view ``path`` (as ``format``, else its best
        format) in a new widget, a ``DataExplorer``, a ``TableSetTab`` or a
        ``ViewTab``, kept until the tab closes ("view_tab_closed").

        Answers at once, {"load_id", "title", "url"} or {"error"}, so that
        the tab opens showing that it loads. The reads run in a worker thread
        (``_loader``), as a preview's; then {"type": "view_tab", "load_id"}
        is sent, with the widget's "model_id" or an "error". Closing the tab
        before cancels the load: what it read is closed.

        A prompt (``ViewWithPrompt``) is shown in a ``ViewTab`` first, sent
        as the view is, with "asking": the tab keeps waiting. The view of the
        answer is read as the first, then sent for the same "load_id": the
        tab shows its widget instead, and lets the prompt's go. The prompt's
        widget shows the errors after an answer, and that it was cancelled.
        """
        path = content.get("path")
        location = self._location_of(path)
        if location is None:
            return {"error": f"{path} has no URL, so it cannot be viewed"}
        load_id = f"view-{next(self._view_tab_ids)}"
        title = _paths.basename(path)
        action = action_id(content.get("action"))
        work = self._preview_work(
            _empty_preview(path, action),
            content.get("format") or None,
            content.get("engine", ...),
            action,
            verb="viewed",
        )
        self._submit_view_tab(load_id, title, work)
        return {"load_id": load_id, "title": title, "url": location.url}

    def _submit_view_tab(
        self,
        load_id: str,
        title: str,
        work: Callable[[], _Loaded],
        asked: ViewTab | None = None,
    ) -> None:
        """Run a view tab's reads, ``work``, as a load, then send what it
        read (see ``_view_tab_request``). ``asked``: the widget of the prompt
        whose answer is read, which shows the errors and a next prompt."""

        def done(loaded: _Loaded) -> None:
            self._view_tab_loads.pop(load_id, None)
            if isinstance(loaded.shown, _Asking):
                self._view_tab_ask(load_id, title, loaded, asked)
                return
            try:
                widget = self._view_tab_widget(loaded, title)
            except Exception as exc:
                discard(loaded, popped=True)
                if asked is not None:
                    asked._show({"kind": "error", "text": error_text(exc)})
                    return
                self.send(
                    {"type": "view_tab", "load_id": load_id, "error": error_text(exc)}
                )
                return
            self._view_tabs[widget.model_id] = widget
            self.send(
                {"type": "view_tab", "load_id": load_id, "model_id": widget.model_id}
            )

        def discard(loaded: _Loaded, popped: bool = False) -> None:
            if not popped:
                self._view_tab_loads.pop(load_id, None)
            if loaded.shown is not None:
                loaded.shown.close()

        load = self._loader.submit(work, done, discard)
        if not load.ended:  # without a loop, it has ended already
            self._view_tab_loads[load_id] = load

    def _view_tab_ask(
        self, load_id: str, title: str, loaded: _Loaded, asked: ViewTab | None
    ) -> None:
        """Show the prompt a view tab's load read, in the widget of the
        previous prompt, ``asked``, else in a new one sent to the tab."""
        asking = loaded.shown
        assert isinstance(asking, _Asking)
        widget = (
            asked
            if asked is not None
            else ViewTab(_LOADING, title=title, label=self._tab_label(loaded.preview))
        )

        def answered(content: dict[str, Any]) -> None:
            self._view_tab_answer(
                load_id,
                title,
                loaded.preview,
                asking=asking,
                widget=widget,
                content=content,
            )

        widget._show(asking.section(), on_close=asking.close, on_answer=answered)
        if asked is not None:
            return
        self._view_tabs[widget.model_id] = widget
        self.send(
            {
                "type": "view_tab",
                "load_id": load_id,
                "model_id": widget.model_id,
                "asking": True,
            }
        )

    def _view_tab_answer(
        self,
        load_id: str,
        title: str,
        preview: dict[str, Any],
        *,
        asking: _Asking,
        widget: ViewTab,
        content: dict[str, Any],
    ) -> None:
        """The user answered the prompt of a view tab, which ``widget``
        shows: read the view of the answer for the tab (see
        ``_view_tab_request``). Ignored if the widget no longer shows it."""
        if (
            content.get("prompt") != asking.id
            or widget._view.get("prompt") != asking.id
        ):
            return
        if content.get("cancel"):
            widget._show(_not_viewed("viewed"))
            asking.close()
            return
        # The load owns the prompt now: the widget no longer closes it.
        widget._show(_LOADING)
        base = {**preview, "sections": [], "error": ""}
        value = content.get("value")
        self._submit_view_tab(
            load_id,
            title,
            lambda: self._read_answer(dict(base), asking, value),
            asked=widget,
        )

    def _tab_label(self, preview: dict[str, Any]) -> str:
        """A view tab's label: the format's, and the engine's."""
        fmt = next(f for f in self._formats if f.name == preview["format"])
        return " · ".join(filter(None, [fmt.label, preview["engine_label"]]))

    def _view_tab_widget(
        self, loaded: _Loaded, title: str
    ) -> DataExplorer | TableSetTab | ViewTab:
        """The widget of a view tab's load (see ``_view_tab_request``), on
        the main thread; ValueError if the item could not be viewed."""
        preview, shown = loaded.preview, loaded.shown
        if preview["error"]:
            raise ValueError(preview["error"])
        if shown is None:
            raise ValueError(f"{title} cannot be viewed in any format")
        label = self._tab_label(preview)
        if isinstance(shown, DataQuery):
            return DataExplorer._of_query(
                shown, self._states, shown.key, title=title, label=label, height="fill"
            )
        if isinstance(shown, TableSet):
            return TableSetTab(shown, title=title, label=label)
        return ViewTab(
            preview["sections"][0], title=title, label=label, on_close=shown.close
        )

    def _view_tab_closed(self, content: dict[str, Any]) -> None:
        """The tab of a "view_tab" closed: its widget ("model_id") is no
        longer kept, and closing it closes its view; a load still running
        ("load_id") is cancelled."""
        load = self._view_tab_loads.pop(content.get("load_id"), None)
        if load is not None:
            load.cancel()
        widget = self._view_tabs.pop(content.get("model_id"), None)
        if widget is not None:
            widget.close()

    def _release_view_tabs(self) -> None:
        """Close the widgets of the explorer's view tabs, and cancel those
        loading: when it closes, and when the launcher shows it again after a
        page reload, which closed the tabs without telling the kernel."""
        self._cancel_view_tab_loads()
        tabs, self._view_tabs = list(self._view_tabs.values()), {}
        for widget in tabs:
            widget.close()

    def _cancel_view_tab_loads(self) -> None:
        """Cancel the view tabs' loads still running: what they read is
        closed when they end."""
        loads, self._view_tab_loads = list(self._view_tab_loads.values()), {}
        for load in loads:
            load.cancel()
