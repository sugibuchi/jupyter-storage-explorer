"""The predefined formats and supports explorers use by default, in order of
preference (``default_formats()``, ``default_supports()``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
