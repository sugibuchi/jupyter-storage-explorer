"""Formats: how explorers detect each kind of data, and handle it with libraries.

``DataFormat`` (base.py, with the ``Target`` it looks at) detects a format,
``FormatSupport`` (support.py) handles its data with one library (previews,
the data browser, recipes), and ``Requirement`` (requirement.py) is a
package one needs. The predefined formats each have a module (delta.py,
parquet.py, excel.py, text.py, images.py), the predefined supports one per
library in the ``supports`` package (imported from there), and
requirements.py has the predefined packages. preview.py has the previews
supports return, and base.py helpers for the code they generate.
``default_formats()`` and ``default_supports()`` (utils.py) create those
explorers use by default.
"""

from jupyter_storage_explorer.formats.base import (
    FILE_ICONS,
    DataFormat,
    Recipe,
    Target,
    detect,
    format_kwargs,
    matching_formats,
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
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
    "DataFormat",
    "DeltaLake",
    "Excel",
    "FormatSupport",
    "Image",
    "InstallPreview",
    "Json",
    "JsonLines",
    "Markdown",
    "MarkdownPreview",
    "MediaPreview",
    "Parquet",
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
