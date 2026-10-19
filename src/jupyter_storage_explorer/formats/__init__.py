"""Formats: how explorers detect, preview and load each kind of data.

``DataFormat`` (format.py, with the ``Target`` it reads) and ``Requirement``
(requirement.py) are the interfaces; the predefined formats each have a
module (delta.py, parquet.py, excel.py, text.py, images.py), and
requirements.py has the predefined packages. preview.py has the preview
sections formats return, and base.py helpers for the code they generate.
``default_formats()`` (utils.py) creates the formats explorers use by default.
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
from jupyter_storage_explorer.formats.parquet import Parquet
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
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text
from jupyter_storage_explorer.formats.utils import (
    DEFAULT_FORMATS,
    FORMAT_OPTIONS,
    check_format_options,
    default_formats,
    explorer_formats,
)

__all__ = [
    "DEFAULT_FORMATS",
    "FILE_ICONS",
    "FORMAT_OPTIONS",
    "Csv",
    "DataFormat",
    "DeltaLake",
    "Excel",
    "Image",
    "InstallPreview",
    "Json",
    "JsonLines",
    "Markdown",
    "MarkdownPreview",
    "MediaPreview",
    "Parquet",
    "Preview",
    "PreviewLimits",
    "Recipe",
    "Requirement",
    "Requirements",
    "TablePreview",
    "Target",
    "Text",
    "TextPreview",
    "TreePreview",
    "check_format_options",
    "default_formats",
    "detect",
    "explorer_formats",
    "format_kwargs",
    "matching_formats",
    "snippet_options",
    "spark_url",
]
