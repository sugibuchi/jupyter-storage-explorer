"""The icons of the formats' files in the explorer's list: each format's
``file_icon``, checked and sent to the frontend (``_format_icons``,
``_file_icon_svgs``; icons.js draws them)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats import FILE_ICONS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer.formats import DataFormat


def format_icons(
    formats: Sequence[DataFormat],
) -> tuple[dict[str, str], dict[str, str]]:
    """The formats' ``file_icon``: format name -> icon name, for the formats
    that set one, and icon name -> SVG markup, for the icons of their own.

    ValueError for an icon name not in ``FILE_ICONS`` (e.g. a typo), an icon
    of their own named as one of them, not SVG, or named as another one.
    """
    icons: dict[str, str] = {}
    svgs: dict[str, str] = {}
    for fmt in formats:
        icon = fmt.file_icon
        if icon is None or fmt.name in icons:
            continue
        where = f"file_icon of format {fmt.name!r}"
        if isinstance(icon, str):
            if icon not in FILE_ICONS:
                raise ValueError(
                    f"unknown {where}: {icon!r}; choose from {list(FILE_ICONS)}, "
                    "or give (name, svg)"
                )
            name = icon
        else:
            name, svg = icon
            if not name or name in (*FILE_ICONS, "folder"):
                raise ValueError(f"{where}: name it other than {list(FILE_ICONS)}")
            if not svg.lstrip().lower().startswith(("<svg", "<?xml")):
                raise ValueError(f"{where}: not SVG markup")
            if svgs.setdefault(name, svg) != svg:
                raise ValueError(f"{where}: another icon is named {name!r}")
        icons[fmt.name] = name
    return icons, svgs
