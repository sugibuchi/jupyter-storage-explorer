"""The widgets' frontend files, in static/."""

from __future__ import annotations

import pathlib
from typing import Any

STATIC = pathlib.Path(__file__).parent / "static"

# Libraries the frontend may ask the kernel for ("vendor"), in static/vendor:
# what Markdown views need (sections.js).
_VENDOR_FILES = frozenset({"marked.esm.js", "purify.es.mjs"})


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
        "sections.js",
        *(f"{widget}/{part}" for part in parts),
        f"{widget}.js",
    )


def css(widget: str) -> str:
    """The stylesheet of a widget: the shared styles, then its own."""
    return _join("common.css", "query.css", "sections.css", f"{widget}.css")


def vendor_source(name: str) -> dict[str, Any]:
    """The answer to a "vendor" request: the source of a bundled library,
    e.g. marked for Markdown views, or {"error"}."""
    if name not in _VENDOR_FILES:
        return {"error": f"unknown library {name!r}"}
    return {"source": (STATIC / "vendor" / name).read_text(encoding="utf-8")}
