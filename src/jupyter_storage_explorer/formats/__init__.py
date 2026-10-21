"""Formats: how explorers detect each kind of data, and handle it with libraries.

``DataFormat`` (base.py, with the ``ItemContext`` it looks at, which reads
the item) detects a format, ``FormatSupport`` (support.py, with its
``SupportOptions`` and ``format_kwargs`` for the code it generates) handles
its data with one engine (views, recipes), an ``Engine`` (engine.py; the
predefined ones are with their supports) is a library users choose, and
``PythonPackage`` (package.py) is a package one needs. The predefined formats each have a
module (delta.py, parquet.py, excel.py, text.py, images.py), the predefined
supports and their engines one per library in the ``supports`` package
(imported from there),
and packages.py has the predefined packages. view.py has the views supports
return. ``default_supports()`` (defaults.py) creates those explorers use by
default; the formats files are detected as are those of the supports.
"""

from jupyter_storage_explorer.formats.base import FILE_ICONS, DataFormat, ItemContext
from jupyter_storage_explorer.formats.defaults import default_supports
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet, ParquetLayout
from jupyter_storage_explorer.formats.support import (
    LIBRARY_DEFAULT,
    Capability,
    FormatOptions,
    FormatSupport,
    LibraryDefault,
    SupportOptions,
    format_arguments,
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
    "LIBRARY_DEFAULT",
    "Capability",
    "Csv",
    "DataFormat",
    "DeltaLake",
    "Engine",
    "Excel",
    "FormatOptions",
    "FormatSupport",
    "Image",
    "ItemContext",
    "Json",
    "JsonLines",
    "LibraryDefault",
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
    "default_supports",
    "format_arguments",
    "format_kwargs",
    "secret_dict_field",
    "secret_field",
]
