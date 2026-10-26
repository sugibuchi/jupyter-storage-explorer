"""The functions given to the widgets' ``on_change`` (and ``on_query_change``)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


class Callbacks:
    """Functions to call with a widget when something of it changes, each once
    however often it is given, in the order given."""

    def __init__(self) -> None:
        self._functions: list[Callable[[Any], Any]] = []

    def register(self, callback: Callable[[Any], Any], *, remove: bool = False) -> None:
        """Add ``callback``, or with ``remove``, stop calling it."""
        if remove:
            if callback in self._functions:
                self._functions.remove(callback)
        elif callback not in self._functions:
            self._functions.append(callback)

    def __call__(self, widget: Any) -> None:
        """Call each function with ``widget``, each one even if another fails.

        They run as the kernel answers the widget's messages, often once a
        load has ended, so what they print or display goes to no cell, nor to
        an ``Output``'s ``with`` block. Their errors are logged, with their
        tracebacks (see _logs.py), which the launcher's log files keep.
        Without IPython (e.g. in tests), they are raised.
        """
        for callback in list(self._functions):
            try:
                callback(widget)
            except Exception:
                from IPython import get_ipython  # noqa: PLC0415

                if get_ipython() is None:
                    raise
                log.exception("The function %r given to the widget failed", callback)
