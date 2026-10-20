"""Formats: how explorers detect each kind of data, and handle it with libraries.

``DataFormat`` (base.py, with the ``ItemContext`` it looks at) detects a format,
``FormatSupport`` (support.py) handles its data with one library (views,
recipes), and ``PythonPackage`` (package.py) is a
package one needs. The predefined formats each have a module (delta.py,
parquet.py, excel.py, text.py, images.py), the predefined supports one per
library in the ``supports`` package (imported from there), and
packages.py has the predefined packages. view.py has the views
supports return, and base.py helpers for the code they generate.
``default_formats()`` and ``default_supports()`` (utils.py) create those
explorers use by default.
"""

from jupyter_storage_explorer.formats.base import (
    FILE_ICONS,
    DataFormat,
    ItemContext,
    child_names,
    detect,
    file_size,
    format_kwargs,
    head,
    head_text,
    library_url,
    matching_formats,
    name_of,
    read_whole,
    snippet_options,
)
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet, ParquetLayout
from jupyter_storage_explorer.formats.support import (
    Capability,
    FormatSupport,
    Recipe,
    SupportChain,
    SupportOptions,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text
from jupyter_storage_explorer.formats.utils import (
    DEFAULT_FORMATS,
    DEFAULT_SUPPORTS,
    default_formats,
    default_supports,
)
from jupyter_storage_explorer.formats.view import (
    InstallView,
    MarkdownView,
    MediaView,
    QueryView,
    TableView,
    TextView,
    TreeView,
    View,
    ViewLimits,
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
    "InstallView",
    "ItemContext",
    "Json",
    "JsonLines",
    "Markdown",
    "MarkdownView",
    "MediaView",
    "Parquet",
    "ParquetLayout",
    "PythonPackage",
    "QueryView",
    "Recipe",
    "SupportChain",
    "SupportOptions",
    "TableView",
    "Text",
    "TextView",
    "TreeView",
    "View",
    "ViewLimits",
    "child_names",
    "default_formats",
    "default_supports",
    "detect",
    "file_size",
    "format_kwargs",
    "head",
    "head_text",
    "library_url",
    "matching_formats",
    "name_of",
    "read_whole",
    "snippet_options",
]
