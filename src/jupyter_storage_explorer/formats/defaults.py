"""The predefined supports explorers use by default, in order of preference
(``default_supports()``): the formats are theirs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.supports.pandas import (
    CsvByPandas,
    ExcelByPandas,
    JsonByPandas,
    JsonLinesByPandas,
    ParquetByPandas,
)
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
    ImageByPillow,
    ImageByPython,
    JsonByPython,
    MarkdownByPython,
    TextByPython,
)

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.support import FormatSupport

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
    JsonByPolars,
    JsonByPandas,
    JsonLinesByPolars,
    JsonLinesByPandas,
    JsonLinesByPySpark,
    MarkdownByPython,
    TextByPython,
    ImageByPython,
    ImageByPillow,
)


def default_supports() -> list[FormatSupport]:
    """The ``DEFAULT_SUPPORTS``, created; their options are given by the
    ``SupportChain`` using them."""
    return [cls() for cls in DEFAULT_SUPPORTS]
