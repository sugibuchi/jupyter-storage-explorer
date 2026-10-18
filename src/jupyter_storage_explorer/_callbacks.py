"""The functions given to the widgets' ``on_change`` (and ``on_query_change``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


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

        They run while the kernel handles the widget's messages, so what they
        print goes to no cell: errors are shown as tracebacks by IPython, in
        the output the functions display into, if any. Without IPython (e.g.
        in tests), they are raised.
        """
        for callback in list(self._functions):
            try:
                callback(widget)
            except Exception:
                from IPython import get_ipython  # noqa: PLC0415

                shell = get_ipython()
                if shell is None:
                    raise
                shell.showtraceback()
