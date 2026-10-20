"""Formats: how explorers detect each kind of data, and handle it with libraries.

``DataFormat`` (base.py, with the ``ItemContext`` it looks at, which reads
the item) detects a format, ``FormatSupport`` (support.py, with its
``SupportOptions`` and ``format_kwargs`` for the code it generates) handles
its data with one library (views, recipes), and ``PythonPackage``
(package.py) is a package one needs. The predefined formats each have a
module (delta.py, parquet.py, excel.py, text.py, images.py), the predefined
supports one per library in the ``supports`` package (imported from there),
and packages.py has the predefined packages. view.py has the views supports
return. ``default_formats()`` and ``default_supports()`` (defaults.py) create
those explorers use by default.
"""

from jupyter_storage_explorer.formats.base import FILE_ICONS, DataFormat, ItemContext
from jupyter_storage_explorer.formats.defaults import default_formats, default_supports
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet, ParquetLayout
from jupyter_storage_explorer.formats.support import (
    Capability,
    FormatOptions,
    FormatSupport,
    SupportOptions,
    format_kwargs,
    secret_dict_field,
    secret_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text
from jupyter_storage_explorer.formats.view import (
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
    "FILE_ICONS",
    "Capability",
    "Csv",
    "DataFormat",
    "DeltaLake",
    "Excel",
    "FormatOptions",
    "FormatSupport",
    "Image",
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
    "SupportOptions",
    "TableView",
    "Text",
    "TextView",
    "TreeView",
    "View",
    "ViewLimits",
    "default_formats",
    "default_supports",
    "format_kwargs",
    "secret_dict_field",
    "secret_field",
]
