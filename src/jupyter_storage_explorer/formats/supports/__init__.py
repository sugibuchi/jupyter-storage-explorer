"""The predefined format supports, a module per library: polars.py,
pandas.py, pyspark.py, fsspec.py, pillow.py, and python.py for those needing
no package, with their options (``PolarsOptions``, ...). Import them from
here, e.g. ``from jupyter_storage_explorer.formats.supports import
CsvByPolars``.

The modules are named after the libraries they use, but import them only
inside methods, absolutely (``import polars``), so the names never shadow the
libraries themselves."""

from jupyter_storage_explorer.formats.supports.fsspec import (
    FsspecOptions,
    JsonByFsspec,
    TextByFsspec,
)
from jupyter_storage_explorer.formats.supports.pandas import (
    CsvByPandas,
    ExcelByPandas,
    JsonByPandas,
    JsonLinesByPandas,
    PandasOptions,
    ParquetByPandas,
)
from jupyter_storage_explorer.formats.supports.pillow import ImageByPillow
from jupyter_storage_explorer.formats.supports.polars import (
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    JsonByPolars,
    JsonLinesByPolars,
    ParquetByPolars,
    PolarsOptions,
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

__all__ = [
    "CsvByPandas",
    "CsvByPolars",
    "CsvByPySpark",
    "DeltaLakeByPolars",
    "DeltaLakeByPolarsOptions",
    "DeltaLakeByPySpark",
    "ExcelByPandas",
    "ExcelByPolars",
    "ExcelByPolarsOptions",
    "FsspecOptions",
    "ImageByPillow",
    "ImageByPython",
    "JsonByFsspec",
    "JsonByPandas",
    "JsonByPolars",
    "JsonByPython",
    "JsonLinesByPandas",
    "JsonLinesByPolars",
    "JsonLinesByPySpark",
    "MarkdownByPython",
    "PandasOptions",
    "ParquetByPandas",
    "ParquetByPolars",
    "ParquetByPySpark",
    "PolarsOptions",
    "TextByFsspec",
    "TextByPython",
]
