"""The tables of options in the plugins' READMEs, from the descriptions of
the options' fields (``option_field``): each table follows a marker naming
the classes whose fields it lists, e.g.

    <!-- options: jupyter_storage_explorer_polars_support.CsvByPolarsOptions -->

A table lists each class's own fields, in order: those its body defines.
Write it, or check that the READMEs are up to date (tests/test_plugin_readmes.py
does):

uv run docs/scripts/option_tables.py [--check]
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pathlib
import re
import sys
from typing import Any

from jupyter_storage_explorer.util import (
    DESCRIPTION,
    LIBRARY_DEFAULT,
    SHOWN_DEFAULT,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
READMES = sorted(ROOT.glob("plugins/*/README.md"))

MARKER = re.compile(r"^<!-- options: (?P<classes>[\w., ]+) -->$")
HEADER = ("Option", "Default", "Meaning")


def own_fields(cls: type) -> list[dataclasses.Field[Any]]:
    """The fields ``cls``'s body defines, in order."""
    own = inspect.get_annotations(cls)
    return [f for f in dataclasses.fields(cls) if f.name in own]


def shown_default(field: dataclasses.Field[Any]) -> str:
    """A field's default, as the table shows it."""
    if SHOWN_DEFAULT in field.metadata:
        return field.metadata[SHOWN_DEFAULT]
    value = field.default
    if value is dataclasses.MISSING or value is LIBRARY_DEFAULT:
        raise ValueError(f"{field.name}: give its shown_default")
    return f"`{value_text(value)}`"


def value_text(value: Any) -> str:
    """``value`` as Python code, strings in double quotes."""
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, tuple):
        items = ", ".join(value_text(v) for v in value)
        return f"({items},)" if len(value) == 1 else f"({items})"
    return repr(value)


def cell(text: str) -> str:
    """Markdown text in a table's cell: lines joined by <br>, pipes escaped."""
    return text.replace("|", "\\|").replace("\n", "<br>")


def rows(classes: list[type]) -> list[tuple[str, str, str]]:
    found = []
    for cls in classes:
        for field in own_fields(cls):
            if DESCRIPTION not in field.metadata:
                raise ValueError(f"{cls.__qualname__}.{field.name}: no description")
            found.append(
                (
                    f"`{field.name}`",
                    cell(shown_default(field)),
                    cell(field.metadata[DESCRIPTION]),
                )
            )
    return found


def table(classes: list[type]) -> list[str]:
    """The table's lines, columns padded to their widest cell."""
    body = rows(classes)
    widths = [max(len(r[i]) for r in [HEADER, *body]) for i in range(3)]

    def line(cells: tuple[str, ...]) -> str:
        return (
            "| "
            + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))
            + " |"
        )

    rule = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return [line(HEADER), rule, *(line(r) for r in body)]


def resolve(names: str) -> list[type]:
    """The classes a marker names, by module and name."""
    classes = []
    for name in names.split(","):
        module, _, attr = name.strip().rpartition(".")
        classes.append(getattr(importlib.import_module(module), attr))
    return classes


def rewritten(text: str) -> str:
    """``text`` with the table after each marker written again."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        out.append(lines[i])
        match = MARKER.match(lines[i])
        i += 1
        if match:
            while i < len(lines) and lines[i].startswith("|"):
                i += 1  # the old table
            out.extend(table(resolve(match["classes"])))
    return "\n".join(out)


def main(check: bool) -> int:
    stale = []
    for readme in READMES:
        raw = readme.read_bytes().decode("utf-8")
        # Kept as checked out, e.g. CRLF on Windows.
        newline = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        new = rewritten(text)
        if new != text:
            stale.append(readme)
            if not check:
                readme.write_text(new, encoding="utf-8", newline=newline)
    for readme in stale:
        verb = "is out of date" if check else "written"
        print(f"{readme.relative_to(ROOT).as_posix()}: {verb}")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
