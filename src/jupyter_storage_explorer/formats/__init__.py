"""Formats: how explorers detect each kind of data, and the views they show.

``DataFormat`` (base.py, with the ``ItemContext`` it looks at, which reads
the item) detects a format. The predefined formats each have a module
(delta.py, parquet.py, excel.py, text.py, images.py). An ``Engine``
(engine.py, with ``EngineOptions``) is a library users choose, and a
``PythonPackage`` a package one needs; packages.py has it with the
predefined packages. views.py has the views actions return.

What explorers do with a format's data are actions, in ``formats.actions``:
functions decorated with ``view`` or ``code``, with their options, an
``ActionOptions`` subclass. ``formats.python`` has the built-in ones, with
their engine, ``PythonEngine``; the other engines' come with their
plugins. defaults.py lists the formats and actions explorers use
whatever plugins are installed.
"""

from jupyter_storage_explorer.formats.actions import ActionOptions
from jupyter_storage_explorer.formats.base import FILE_ICONS, DataFormat, ItemContext
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine, EngineOptions
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import (
    Avif,
    Bmp,
    Gif,
    Ico,
    Image,
    Jpeg,
    Png,
    Webp,
)
from jupyter_storage_explorer.formats.local_files import (
    CacheStatus,
    LocalFileCache,
    local_file_cache,
)
from jupyter_storage_explorer.formats.packages import PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet, ParquetLayout
from jupyter_storage_explorer.formats.text import (
    Conf,
    Csv,
    Html,
    Ini,
    Java,
    JavaScript,
    Json,
    JsonLines,
    Log,
    Markdown,
    Properties,
    PythonScript,
    ReStructuredText,
    RScript,
    Scala,
    ShellScript,
    Sql,
    Svg,
    Text,
    Toml,
    TypeScript,
    Xml,
    Yaml,
)
from jupyter_storage_explorer.formats.user_defined import UserDefinedFormat, file_format
from jupyter_storage_explorer.formats.views import (
    JupyterWidgetView,
    Leaf,
    MarkdownView,
    MediaView,
    Node,
    QueryView,
    TableSetView,
    TableView,
    TextView,
    TreeView,
    View,
    ViewLimits,
    ViewWithChoice,
    ViewWithConfirmation,
    ViewWithInput,
    ViewWithPrompt,
)

__all__ = [
    "FILE_ICONS",
    "ActionOptions",
    "Avif",
    "Bmp",
    "CacheStatus",
    "Conf",
    "Csv",
    "DataFormat",
    "DeltaLake",
    "Engine",
    "EngineOptions",
    "Excel",
    "Gif",
    "Html",
    "Ico",
    "Image",
    "Ini",
    "ItemContext",
    "Java",
    "JavaScript",
    "Jpeg",
    "Json",
    "JsonLines",
    "JupyterWidgetView",
    "Leaf",
    "LocalFileCache",
    "Log",
    "Markdown",
    "MarkdownView",
    "MediaView",
    "Node",
    "Parquet",
    "ParquetLayout",
    "Png",
    "Properties",
    "PythonPackage",
    "PythonScript",
    "QueryView",
    "RScript",
    "ReStructuredText",
    "Scala",
    "ShellScript",
    "Sql",
    "Svg",
    "TableSetView",
    "TableView",
    "Text",
    "TextView",
    "Toml",
    "TreeView",
    "TypeScript",
    "UserDefinedFormat",
    "View",
    "ViewLimits",
    "ViewWithChoice",
    "ViewWithConfirmation",
    "ViewWithInput",
    "ViewWithPrompt",
    "Webp",
    "Xml",
    "Yaml",
    "file_format",
    "local_file_cache",
]
