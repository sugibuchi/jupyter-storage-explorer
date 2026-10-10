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

DEFAULT_FORMATS: list[DataFormat] = [
    DeltaLake(),
    Parquet(),
    Csv(),
    Excel(),
    Json(),
    JsonLines(),
    Markdown(),
    Text(),
    Image(),
]

__all__ = [
    "DEFAULT_FORMATS",
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
    "detect",
    "format_args",
    "matching_formats",
]
