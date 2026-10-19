"""The default formats, creating them with the explorers' ``format_options``,
and the formats' file icons."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.format import FILE_ICONS
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from jupyter_storage_explorer.formats.format import DataFormat

# The formats explorers use unless given others; ``default_formats`` creates them.
# On a tie in priority, the format listed first wins.
DEFAULT_FORMATS: tuple[type[DataFormat], ...] = (
    DeltaLake,
    Parquet,
    Csv,
    Excel,
    Json,
    JsonLines,
    Markdown,
    Text,
    Image,
)

# Every option the default formats take; add new ones here too.
FORMAT_OPTIONS = (
    "polars_storage_options",
    "polars_credential_provider",
    "fsspec_storage_options",
    "pandas_storage_options",
    "polars_delta_table_options",
    "polars_delta_use_pyarrow",
    "polars_delta_pyarrow_options",
)


def check_format_options(options: Mapping[str, Any]) -> None:
    """Raise ValueError if ``options`` has names not in ``FORMAT_OPTIONS``, e.g. a typo."""
    unknown = options.keys() - set(FORMAT_OPTIONS)
    if unknown:
        raise ValueError(
            f"unknown format_options {sorted(unknown)}; choose from {list(FORMAT_OPTIONS)}"
        )


def default_formats(options: Mapping[str, Any] | None = None) -> list[DataFormat]:
    """The ``DEFAULT_FORMATS``, each created with all of ``options`` as keyword
    arguments, e.g. ``{"polars_storage_options": {...},
    "polars_delta_use_pyarrow": True}``; each format uses the ones it takes."""
    options = options or {}
    check_format_options(options)
    return [cls(**options) for cls in DEFAULT_FORMATS]


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


def explorer_formats(
    formats: Sequence[DataFormat] | None, format_options: Mapping[str, Any] | None
) -> list[DataFormat]:
    """The formats an explorer uses: ``formats`` if given, else the default
    ones created with ``format_options``. Giving both is a TypeError."""
    if formats is None:
        return default_formats(format_options)
    if format_options is not None:
        raise TypeError("formats cannot be combined with format_options")
    return list(formats)
