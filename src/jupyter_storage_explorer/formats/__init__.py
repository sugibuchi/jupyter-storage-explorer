"""Formats: how explorers detect each kind of data, and handle it with libraries.

``DataFormat`` (format.py, with the ``Target`` it looks at) detects a format,
``FormatSupport`` (support.py) handles its data with one library (previews,
the data browser, recipes), and ``Requirement`` (requirement.py) is a
package one needs. The predefined formats each have a module (delta.py,
parquet.py, excel.py, text.py, images.py), the predefined supports one per
library in supports/ (polars.py, pandas.py, pyspark.py, fsspec.py,
pillow.py, and python.py for those needing no package), and
requirements.py has the predefined packages. preview.py has the preview
sections supports return, and base.py helpers for the code they generate.
``default_formats()`` and ``default_supports()`` (utils.py) create those
explorers use by default.
"""

from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.format import (
    FILE_ICONS,
    DataFormat,
    Recipe,
    Target,
    detect,
    matching_formats,
)
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet, ParquetLayout
from jupyter_storage_explorer.formats.preview import (
    InstallPreview,
    MarkdownPreview,
    MediaPreview,
    Preview,
    PreviewLimits,
    TablePreview,
    TextPreview,
    TreePreview,
)
from jupyter_storage_explorer.formats.requirement import Requirement, Requirements
from jupyter_storage_explorer.formats.support import (
    Capability,
    FormatSupport,
    SupportChain,
)
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
from jupyter_storage_explorer.formats.utils import (
    DEFAULT_FORMATS,
    DEFAULT_SUPPORTS,
    create_supports,
    default_formats,
    default_supports,
)

__all__ = [
    "DEFAULT_FORMATS",
    "DEFAULT_SUPPORTS",
    "FILE_ICONS",
    "Capability",
    "Csv",
    "CsvByPandas",
    "CsvByPolars",
    "CsvByPySpark",
    "DataFormat",
    "DeltaLake",
    "DeltaLakeByPolars",
    "DeltaLakeByPySpark",
    "Excel",
    "ExcelByPandas",
    "ExcelByPolars",
    "FormatSupport",
    "Image",
    "ImageByPillow",
    "ImageByPython",
    "InstallPreview",
    "Json",
    "JsonByFsspec",
    "JsonByPandas",
    "JsonByPolars",
    "JsonByPython",
    "JsonLines",
    "JsonLinesByPandas",
    "JsonLinesByPolars",
    "JsonLinesByPySpark",
    "Markdown",
    "MarkdownByPython",
    "MarkdownPreview",
    "MediaPreview",
    "Parquet",
    "ParquetByPandas",
    "ParquetByPolars",
    "ParquetByPySpark",
    "ParquetLayout",
    "Preview",
    "PreviewLimits",
    "Recipe",
    "Requirement",
    "Requirements",
    "SupportChain",
    "TablePreview",
    "Target",
    "Text",
    "TextByFsspec",
    "TextByPython",
    "TextPreview",
    "TreePreview",
    "create_supports",
    "default_formats",
    "default_supports",
    "detect",
    "format_kwargs",
    "matching_formats",
    "snippet_options",
    "spark_url",
]
