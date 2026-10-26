"""The functions given to the widgets' ``on_change`` (and ``on_query_change``)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


def _in_ipython() -> bool:
    from IPython import get_ipython  # noqa: PLC0415

    return get_ipython() is not None


class Callbacks:
    """Functions to call with a widget when something of it changes, each once
    however often it is given, in the order given.

    In a kernel, they are called as the kernel handles a message the page
    sends back when asked (see ``__call__``), so that an ``Output``'s ``with``
    block shows what they display. ``name`` tells the page's answer which
    functions it is for, as a widget may have several of them."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._functions: list[Callable[[Any], Any]] = []
        # Asked the page to call them back, which it has not done yet.
        self._pending = False

    def register(self, callback: Callable[[Any], Any], *, remove: bool = False) -> None:
        """Add ``callback``, or with ``remove``, stop calling it."""
        if remove:
            if callback in self._functions:
                self._functions.remove(callback)
        elif callback not in self._functions:
            self._functions.append(callback)

    def __call__(self, widget: Any) -> None:
        """Call each function with ``widget``, or in a kernel, ask the page to.

        Changes often show once a load has ended, after the kernel has replied
        to the message that started it. JupyterLab then routes no output to an
        ``Output``'s ``with`` block, so what the functions display would be
        lost. The page's answer, a "callbacks" message, is a new request, in
        whose handling they run (see ``answer``). Several changes before it
        comes make one call. Without IPython (e.g. in tests), they are called
        at once.
        """
        if not self._functions:
            return
        if not _in_ipython():
            self._run(widget)
        elif not self._pending:
            self._pending = True
            widget.send({"type": "callbacks", "name": self._name})

    def answer(self, widget: Any, content: dict[str, Any]) -> bool:
        """Call the functions if ``content``, a "callbacks" message from the
        page, asks for them, as asked by ``__call__``. Each view of the widget
        answers, but the functions run once. True if the message was theirs."""
        if content.get("name") != self._name:
            return False
        if self._pending:
            self._pending = False
            self._run(widget)
        return True

    def _run(self, widget: Any) -> None:
        """Call each function with ``widget``, each one even if another fails.

        What they display outside an ``Output``'s ``with`` block goes to no
        cell. Their errors are logged, with their tracebacks (see _logs.py),
        which the launcher's log files keep. Without IPython, they are raised.
        """
        for callback in list(self._functions):
            try:
                callback(widget)
            except Exception:
                if not _in_ipython():
                    raise
                log.exception("The function %r given to the widget failed", callback)
