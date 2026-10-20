"""The default formats and supports, creating the supports with the
explorers' ``format_options``, and the formats' file icons."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import FILE_ICONS
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import FormatSupport
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
    from collections.abc import Mapping, Sequence

    from jupyter_storage_explorer.formats.base import DataFormat

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
# creates them. In order of preference, format by format: for previews and
# the data browser, the first installed is used, and "Python code" shows them in this order.
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

# In format_options, the options of a library for all formats.
ALL_FORMATS = "*"


def default_formats() -> list[DataFormat]:
    """The ``DEFAULT_FORMATS``, created."""
    return [cls() for cls in DEFAULT_FORMATS]


def default_supports(
    options: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> list[FormatSupport]:
    """The ``DEFAULT_SUPPORTS``, created with ``options`` (see ``create_supports``)."""
    return create_supports(DEFAULT_SUPPORTS, options)


def _support_options(cls: type[FormatSupport]) -> frozenset[str]:
    """The options a support class takes: its ``__init__``'s keyword-only
    arguments."""
    parameters = inspect.signature(cls.__init__).parameters.values()
    return frozenset(p.name for p in parameters if p.kind is p.KEYWORD_ONLY)


def create_supports(
    supports: Sequence[type[FormatSupport] | FormatSupport],
    options: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    format_names: Sequence[str] | None = None,
) -> list[FormatSupport]:
    """``supports``, those given as classes created with ``options``, the
    others as they are.

    ``options`` are by library (a support's ``use``'s package), then format
    name, or ``"*"`` for all formats, e.g. ``{"polars": {"*":
    {"storage_options": {...}}, "delta": {"use_pyarrow": True}}}``: a support
    class gets those of its library for all formats, then for its format
    (``format.name``), each only if its ``__init__`` takes it.

    ValueError for a library no class has, a format neither in
    ``format_names`` nor of a class, or an option no class of the
    library (for that format) takes: a typo would otherwise be ignored.
    TypeError for an item that is no FormatSupport.
    """
    classes = []
    for support in supports:
        cls = support if isinstance(support, type) else type(support)
        if not issubclass(cls, FormatSupport):
            raise TypeError(f"not a FormatSupport: {support!r}")
        if isinstance(support, type):
            classes.append(support)
    options = options or {}
    _check_options(options, classes, format_names)
    created = []
    for support in supports:
        if not isinstance(support, type):
            created.append(support)
            continue
        library = options.get(support.library(), {}) if support.use else {}
        merged = {
            **library.get(ALL_FORMATS, {}),
            **library.get(support.format.name, {}),
        }
        taken = _support_options(support)
        created.append(support(**{k: v for k, v in merged.items() if k in taken}))
    return created


def _check_options(
    options: Mapping[str, Any],
    classes: Sequence[type[FormatSupport]],
    format_names: Sequence[str] | None,
) -> None:
    """ValueError for ``options`` that no class takes (see ``create_supports``)."""
    libraries: dict[str, list[type[FormatSupport]]] = {}
    for cls in classes:
        if cls.use is not None:
            libraries.setdefault(cls.library(), []).append(cls)
    format_names = list(
        dict.fromkeys([*(format_names or ()), *(cls.format.name for cls in classes)])
    )
    for library, by_format in options.items():
        if library not in libraries:
            raise ValueError(
                f"format_options: unknown library {library!r}; "
                f"choose from {sorted(libraries)}"
            )
        if not isinstance(by_format, dict):
            raise ValueError(
                f"format_options[{library!r}] must be a dict of format names "
                f"(or {ALL_FORMATS!r}) to options"
            )
        for name, values in by_format.items():
            _check_format_options(
                f"format_options[{library!r}][{name!r}]",
                name,
                values,
                libraries[library],
                format_names,
            )


def _check_format_options(
    where: str,
    name: str,
    values: Any,
    classes: Sequence[type[FormatSupport]],
    format_names: Sequence[str],
) -> None:
    """ValueError for options of a library for format ``name`` (or all) that
    none of its ``classes`` for it takes."""
    if name != ALL_FORMATS and name not in format_names:
        raise ValueError(
            f"{where}: unknown format; choose from {[ALL_FORMATS, *format_names]}"
        )
    if not isinstance(values, dict):
        raise ValueError(f"{where} must be a dict of options")
    taken: set[str] = set()
    for cls in classes:
        if name in (ALL_FORMATS, cls.format.name):
            taken |= _support_options(cls)
    unknown = values.keys() - taken
    if unknown:
        raise ValueError(
            f"{where}: unknown options {sorted(unknown)}; choose from {sorted(taken)}"
        )


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
