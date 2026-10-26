"""Formats: how explorers detect each kind of data.

``DataFormat`` (base.py) detects a format, looking at an ``ItemContext``.
The predefined formats each have a module (delta.py, parquet.py, excel.py,
text.py, images.py), and user_defined.py has ``file_format``, for formats
of a few lines. defaults.py lists the formats explorers detect whatever
plugins are installed.

What explorers do with a format's data are actions, in the ``actions``
package, which return the views of ``views``.
"""

from jupyter_storage_explorer.formats.base import FILE_ICONS, DataFormat
from jupyter_storage_explorer.formats.delta import DeltaLake
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

__all__ = [
    "FILE_ICONS",
    "Avif",
    "Bmp",
    "Conf",
    "Csv",
    "DataFormat",
    "DeltaLake",
    "Excel",
    "Gif",
    "Html",
    "Ico",
    "Image",
    "Ini",
    "Java",
    "JavaScript",
    "Jpeg",
    "Json",
    "JsonLines",
    "Log",
    "Markdown",
    "Parquet",
    "ParquetLayout",
    "Png",
    "Properties",
    "PythonScript",
    "RScript",
    "ReStructuredText",
    "Scala",
    "ShellScript",
    "Sql",
    "Svg",
    "Text",
    "Toml",
    "TypeScript",
    "UserDefinedFormat",
    "Webp",
    "Xml",
    "Yaml",
    "file_format",
]
