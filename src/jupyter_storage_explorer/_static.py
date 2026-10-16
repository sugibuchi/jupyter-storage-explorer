"""The widgets' frontend files, in static/."""

from __future__ import annotations

import pathlib

STATIC = pathlib.Path(__file__).parent / "static"


def _join(*names: str) -> str:
    return "\n".join((STATIC / name).read_text(encoding="utf-8") for name in names)


def esm(widget: str) -> str:
    """The module of a widget (e.g. "storage_explorer"): the shared code, its
    parts (the files of static/<widget>/, if any), then its own file.

    anywidget modules cannot import files next to them, so they are joined
    here; the shared files and the parts only define functions and
    constants, and the widget's file exports it.
    """
    parts = sorted(p.name for p in (STATIC / widget).glob("*.js"))
    return _join(
        "icons.js",
        "common.js",
        "query.js",
        *(f"{widget}/{part}" for part in parts),
        f"{widget}.js",
    )


def css(widget: str) -> str:
    """The stylesheet of a widget: the shared styles, then its own."""
    return _join("common.css", "query.css", f"{widget}.css")
