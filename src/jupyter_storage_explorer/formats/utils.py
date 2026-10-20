"""The default formats and supports, and the formats' file icons."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import FILE_ICONS
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.supports.fsspec import JsonByFsspec, TextByFsspec
from jupyter_storage_explorer.formats.supports.pandas import (
    CsvByPandas,
    ExcelByPandas,
    JsonByPandas,
    JsonLinesByPandas,
    ParquetByPandas,
)
from jupyter_storage_explorer.formats.supports.pillow import ImageByPillow
from jupyter_storage_explorer.formats.supports.polars import (
    CsvByPolars,
    DeltaLakeByPolars,
    ExcelByPolars,
    JsonByPolars,
    JsonLinesByPolars,
    ParquetByPolars,
)
from jupyter_storage_explorer.formats.supports.pyspark import (
    CsvByPySpark,
    DeltaLakeByPySpark,
    JsonLinesByPySpark,
    ParquetByPySpark,
)
from jupyter_storage_explorer.formats.supports.python import (
    ImageByPython,
    JsonByPython,
    MarkdownByPython,
    TextByPython,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport

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

# The supports explorers use after those they are given; ``default_supports``
# creates them. In order of preference, format by format: for views, the
# first installed is used, and "Python code" shows them in this order.
# MarkdownByPython comes before TextByPython: Markdown is a Text format.
DEFAULT_SUPPORTS: tuple[type[FormatSupport], ...] = (
    DeltaLakeByPolars,
    DeltaLakeByPySpark,
    ParquetByPolars,
    ParquetByPandas,
    ParquetByPySpark,
    CsvByPolars,
    CsvByPandas,
    CsvByPySpark,
    ExcelByPolars,
    ExcelByPandas,
    JsonByPython,
    JsonByFsspec,
    JsonByPolars,
    JsonByPandas,
    JsonLinesByPolars,
    JsonLinesByPandas,
    JsonLinesByPySpark,
    MarkdownByPython,
    TextByPython,
    TextByFsspec,
    ImageByPython,
    ImageByPillow,
)


def default_formats() -> list[DataFormat]:
    """The ``DEFAULT_FORMATS``, created."""
    return [cls() for cls in DEFAULT_FORMATS]


def default_supports() -> list[FormatSupport]:
    """The ``DEFAULT_SUPPORTS``, created; their options are given by the
    ``SupportChain`` using them."""
    return [cls() for cls in DEFAULT_SUPPORTS]


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
