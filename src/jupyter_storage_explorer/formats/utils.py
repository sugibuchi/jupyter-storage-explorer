"""The default formats, and creating them with the explorers' ``format_options``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
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
