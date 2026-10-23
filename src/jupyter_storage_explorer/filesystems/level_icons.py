"""Icons of folders by their level (``FileSystemMapper.level``), as CSS a
mapper gives in its ``css``: ``level_icon_css``, and the predefined mappers'
icons (``ICONS``).

The icons are SVG images used as masks, so that they are drawn in one colour:
the storage's (``--jse-storage-color``), else JupyterLab's grey, and the
selection's in selected rows. They are from Material Design Icons (filled;
Apache License 2.0), the bucket, the hard disk and Databricks' from
Pictogrammers' Material Design Icons (Apache License 2.0), and two from
Material Symbols (see static/vendor/README.md). Not the clouds' own
pictograms, whose licences cover diagrams and documents only.
"""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def _svg(path: str, view_box: str = "0 0 24 24") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}"><path d="{path}"/></svg>'


# Material Symbols' grid, for the icons drawn on it; the others are on the
# 24-pixel one.
_SYMBOLS = "0 -960 960 960"

# The predefined mappers' icons, by name: an SVG image each.
ICONS = {
    # An Azure account; the top of S3 or GCS, holding the buckets.
    "cloud": _svg(
        "M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z"
    ),
    # Material's inventory_2: a box, for an Azure container.
    "box": _svg(
        "M20 2H4c-1 0-2 .9-2 2v3.01c0 .72.43 1.34 1 1.69V20c0 1.1 1.1 2 2 2h14c.9 0 2-.9 2-2V8.7c.57-.35 1-.97 1-1.69V4c0-1.1-1-2-2-2zm-5 12H9v-2h6v2zm5-7H4V4h16v3z"
    ),
    "bucket": _svg("M3 4H21V7H20L17.5 21H6.5L4 7H3V4Z"),
    # Material's dns: a server, for an SFTP host.
    "server": _svg(
        "M20 13H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zM7 19c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM20 3H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zM7 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"
    ),
    "harddisk": _svg(
        "M6,2H18A2,2 0 0,1 20,4V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2M12,4A6,6 0 0,0 6,10C6,13.31 8.69,16 12.1,16L11.22,13.77C10.95,13.29 11.11,12.68 11.59,12.4L12.45,11.9C12.93,11.63 13.54,11.79 13.82,12.27L15.74,14.69C17.12,13.59 18,11.9 18,10A6,6 0 0,0 12,4M12,9A1,1 0 0,1 13,10A1,1 0 0,1 12,11A1,1 0 0,1 11,10A1,1 0 0,1 12,9M7,18A1,1 0 0,0 6,19A1,1 0 0,0 7,20A1,1 0 0,0 8,19A1,1 0 0,0 7,18M12.09,13.27L14.58,19.58L17.17,18.08L12.95,12.77L12.09,13.27Z"
    ),
    # Material's memory: a chip, for fsspec's memory filesystem.
    "chip": _svg(
        "M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z"
    ),
    # Databricks. Unity Catalog: its catalogs (MDI's bookshelf), a catalog
    # (Material Symbols' book_2), a schema (MDI's database), a volume
    # (Material Symbols' files); /Workspace (Material's work).
    "bookshelf": _svg(
        "M9 3V18H12V3H9M12 5L16 18L19 17L15 4L12 5M5 5V18H8V5H5M3 19V21H21V19H3Z"
    ),
    "book2": _svg(
        "M290-80q-54 0-92-38t-38-92v-540q0-54 38-92t92-38h510v600q-26 0-43 21t-17 49q0 28 17 49t43 21v60H290Zm30-260h60v-480h-60v480Zm-30 200h409q-9-15-14-33t-5-37q0-20 5-37.5t15-32.5H290q-29 0-49.5 20.5T220-210q0 29 20.5 49.5T290-140Z",
        _SYMBOLS,
    ),
    "files": _svg(
        "M140-160q-24.75 0-42.37-17.63Q80-195.25 80-220v-160h360q24.75 0 42.38-17.63Q500-415.25 500-440v-360h320q24.75 0 42.38 17.62Q880-764.75 880-740v520q0 24.75-17.62 42.37Q844.75-160 820-160H140ZM80-406v-254q0-24.75 17.63-42.38Q115.25-720 140-720h254L80-406Zm119-34 241-241v241H199Z",
        _SYMBOLS,
    ),
    "work": _svg(
        "M20 6h-4V4c0-1.11-.89-2-2-2h-4c-1.11 0-2 .89-2 2v2H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-6 0h-4V4h4v2z"
    ),
    "database": _svg(
        "M12,3C7.58,3 4,4.79 4,7C4,9.21 7.58,11 12,11C16.42,11 20,9.21 20,7C20,4.79 16.42,3 12,3M4,9V12C4,14.21 7.58,16 12,16C16.42,16 20,14.21 20,12V9C20,11.21 16.42,13 12,13C7.58,13 4,11.21 4,9M4,14V17C4,19.21 7.58,21 12,21C16.42,21 20,19.21 20,17V14C20,16.21 16.42,18 12,18C7.58,18 4,16.21 4,14Z"
    ),
    # Workspace files: Material's group, person and folder_shared; MDI's
    # source-repository(-multiple) for Repos and a repository.
    "group": _svg(
        "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"
    ),
    "person": _svg(
        "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"
    ),
    "folder-shared": _svg(
        "M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-5 3c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm4 8h-8v-1c0-1.33 2.67-2 4-2s4 .67 4 2v1z"
    ),
    "repositories": _svg(
        "M8,0H20A2,2 0 0,1 22,2V18A2,2 0 0,1 20,20H8A2,2 0 0,1 6,18V2A2,2 0 0,1 8,0M14.75,11.5C17.5,11.5 18.24,9.47 18.43,8.4C19.34,8.11 20,7.26 20,6.25C20,5 19,4 17.75,4C16.5,4 15.5,5 15.5,6.25C15.5,7.19 16.07,8 16.89,8.33C16.67,9 16,10 14,10C12.62,10 11.66,10.35 11,10.84V6.87C11.87,6.56 12.5,5.73 12.5,4.75C12.5,3.5 11.5,2.5 10.25,2.5C9,2.5 8,3.5 8,4.75C8,5.73 8.63,6.56 9.5,6.87V13.13C8.63,13.44 8,14.27 8,15.25C8,16.5 9,17.5 10.25,17.5C11.5,17.5 12.5,16.5 12.5,15.25C12.5,14.32 11.94,13.5 11.13,13.18C11.41,12.5 12.23,11.5 14.75,11.5M10.25,14.5A0.75,0.75 0 0,1 11,15.25A0.75,0.75 0 0,1 10.25,16A0.75,0.75 0 0,1 9.5,15.25A0.75,0.75 0 0,1 10.25,14.5M10.25,4A0.75,0.75 0 0,1 11,4.75A0.75,0.75 0 0,1 10.25,5.5A0.75,0.75 0 0,1 9.5,4.75A0.75,0.75 0 0,1 10.25,4M17.75,5.5A0.75,0.75 0 0,1 18.5,6.25A0.75,0.75 0 0,1 17.75,7A0.75,0.75 0 0,1 17,6.25A0.75,0.75 0 0,1 17.75,5.5M16,22V24H4A2,2 0 0,1 2,22V6H4V22H16Z"
    ),
    "repository": _svg(
        "M6,2H18A2,2 0 0,1 20,4V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2M12.75,13.5C15.5,13.5 16.24,11.47 16.43,10.4C17.34,10.11 18,9.26 18,8.25C18,7 17,6 15.75,6C14.5,6 13.5,7 13.5,8.25C13.5,9.19 14.07,10 14.89,10.33C14.67,11 14,12 12,12C10.62,12 9.66,12.35 9,12.84V8.87C9.87,8.56 10.5,7.73 10.5,6.75C10.5,5.5 9.5,4.5 8.25,4.5C7,4.5 6,5.5 6,6.75C6,7.73 6.63,8.56 7.5,8.87V15.13C6.63,15.44 6,16.27 6,17.25C6,18.5 7,19.5 8.25,19.5C9.5,19.5 10.5,18.5 10.5,17.25C10.5,16.32 9.94,15.5 9.13,15.18C9.41,14.5 10.23,13.5 12.75,13.5M8.25,16.5A0.75,0.75 0 0,1 9,17.25A0.75,0.75 0 0,1 8.25,18A0.75,0.75 0 0,1 7.5,17.25A0.75,0.75 0 0,1 8.25,16.5M8.25,6A0.75,0.75 0 0,1 9,6.75A0.75,0.75 0 0,1 8.25,7.5A0.75,0.75 0 0,1 7.5,6.75A0.75,0.75 0 0,1 8.25,6M15.75,7.5A0.75,0.75 0 0,1 16.5,8.25A0.75,0.75 0 0,1 15.75,9A0.75,0.75 0 0,1 15,8.25A0.75,0.75 0 0,1 15.75,7.5Z"
    ),
    # Legacy DBFS's top folders: MDI's folder-clock.
    "folder-clock": _svg(
        "M3,4C1.89,4 1,4.89 1,6V18A2,2 0 0,0 3,20H10.26C11.57,21.88 13.71,23 16,23A7,7 0 0,0 23,16C23,14.17 22.28,12.42 21,11.11V8C21,6.89 20.1,6 19,6H11L9,4H3M16,11A5,5 0 0,1 21,16A5,5 0 0,1 16,21A5,5 0 0,1 11,16A5,5 0 0,1 16,11M15,12V17L18.61,19.16L19.36,17.94L16.5,16.25V12H15Z"
    ),
}


def level_icon_css(icons: Mapping[str, str], color: str | None = None) -> str:
    """CSS giving the folders of each level an icon of their own, for a
    ``FileSystemMapper``'s ``css``.

    Each icon is drawn in one colour, as a mask: the storage's colour, else
    JupyterLab's grey, and the selection's colour in selected rows. Only the
    image's shape counts, not its colours.

    Parameters
    ----------
    icons : mapping of str to str
        An SVG image by level, as ``level`` gives them, e.g.
        ``{"catalog": '<svg xmlns="http://www.w3.org/2000/svg" ...>...</svg>'}``.
    color : str, optional
        The storage's colour, a CSS colour, e.g. ``"#0078d4"``: the
        ``--jse-storage-color`` of the explorer while it shows the storage.

    Returns
    -------
    str
        The CSS, scoped by the explorer to its mapper's storages.

    Examples
    --------
    >>> class CatalogMapper(FileSystemMapper):
    ...     classes = ("mypackage.CatalogFileSystem",)
    ...     levels = ("catalog",)
    ...     css = level_icon_css({"catalog": CATALOG_SVG}, color="#ff3621")
    """
    rules = []
    if color:
        rules.append(f"& {{ --jse-storage-color: {color}; }}")
    if icons:
        each = ", ".join(_level(level) for level in icons)
        rules += [
            f":is({each}) .jse-icon svg {{ display: none; }}",
            f":is({each}) .jse-icon::before {{"
            ' content: ""; flex: none; width: 16px; height: 16px;'
            " background-color: var(--jse-storage-color, var(--jse-icon));"
            " mask: center / contain no-repeat; }",
            # The selection's colour, as the other icons of selected rows. In
            # :where(), so that users' CSS starting with .jse-browser still
            # overrides it.
            f":where(.jse-selected, .jse-active):is({each}) .jse-icon::before {{"
            " background-color: var(--jse-selected-fg); }",
        ]
        rules += [
            f"{_level(level)} .jse-icon::before {{ mask-image: {_url(svg)}; }}"
            for level, svg in icons.items()
        ]
    return "\n".join(rules)


def _level(level: str) -> str:
    return f'[data-fs-level="{css_string(level)}"]'


def _url(svg: str) -> str:
    return f'url("data:image/svg+xml,{urllib.parse.quote(svg, safe="")}")'


def css_string(text: str) -> str:
    """``text`` inside a CSS string in double quotes."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\a ")
