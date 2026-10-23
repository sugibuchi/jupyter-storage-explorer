"""How the explorer shows each storage, as its mapper's ``css`` says (e.g.
the icons of its levels): scoped to the explorer while it shows one of the
mapper's storages, and sent to the frontend (``_mapper_css``, and the
mapper of the storage shown, ``_fs_mapper``), which puts each mapper's on
the page once (mapper_css.js)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.filesystems.level_icons import css_string

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jupyter_storage_explorer.filesystems import FileSystemMapper


def mapper_key(mapper: FileSystemMapper) -> str:
    """The name the page knows ``mapper``'s CSS by: its class's qualified
    name, the same in every kernel; "" for a mapper without CSS."""
    cls = type(mapper)
    return f"{cls.__module__}.{cls.__qualname__}" if mapper.css else ""


def mapper_styles(mappers: Iterable[FileSystemMapper]) -> dict[str, str]:
    """The CSS of ``mappers``, those that have some, by ``mapper_key``: each
    nested in the selector of the explorer showing one of its storages.

    In ``:where()``, so that the explorer adds no weight to the mapper's
    selectors: users' CSS starting with ``.jse-browser`` overrides it.
    """
    styles = {}
    for mapper in mappers:
        if key := mapper_key(mapper):
            selector = f'.jse-browser[data-fs-mapper="{css_string(key)}"]'
            styles.setdefault(key, f":where({selector}) {{\n{mapper.css}\n}}")
    return styles
