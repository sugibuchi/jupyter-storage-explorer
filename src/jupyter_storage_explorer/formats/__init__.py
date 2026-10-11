"""Detection, preview and load snippets for each kind of data."""

from jupyter_storage_explorer.formats.base import (
    DataFormat,
    InstallPreview,
    MarkdownPreview,
    MediaPreview,
    Preview,
    PreviewLimits,
    Recipe,
    Requirement,
    Requirements,
    TablePreview,
    Target,
    TextPreview,
    TreePreview,
    detect,
    format_args,
    matching_formats,
)
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
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
    "format_args",
    "matching_formats",
]
