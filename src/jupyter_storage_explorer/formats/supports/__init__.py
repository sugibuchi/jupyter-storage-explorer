"""The predefined format supports and their engines, a module per library:
polars.py, pandas.py, pyspark.py, pillow.py, and python.py for those without
an engine, needing only the explorer's own packages (the built-in views, and
code reading files with fsspec), with their options (``PolarsOptions``, ...). Import them from
here, e.g. ``from jupyter_storage_explorer.formats.supports import
CsvByPolars, PolarsEngine``.

The modules are named after the libraries they use, but import them only
inside methods, absolutely (``import polars``), so the names never shadow the
libraries themselves."""

from jupyter_storage_explorer.formats.supports.pandas import (
    CsvByPandas,
    ExcelByPandas,
    JsonByPandas,
    JsonLinesByPandas,
    PandasEngine,
    PandasOptions,
    ParquetByPandas,
)
from jupyter_storage_explorer.formats.supports.pillow import ImageByPillow, PillowEngine
from jupyter_storage_explorer.formats.supports.polars import (
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    JsonByPolars,
    JsonLinesByPolars,
    ParquetByPolars,
    PolarsEngine,
    PolarsOptions,
)
from jupyter_storage_explorer.formats.supports.pyspark import (
    CsvByPySpark,
    DeltaLakeByPySpark,
    JsonLinesByPySpark,
    ParquetByPySpark,
    PySparkEngine,
)
from jupyter_storage_explorer.formats.supports.python import (
    FsspecOptions,
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
    "JsonByPandas",
    "JsonByPolars",
    "JsonByPython",
    "JsonLinesByPandas",
    "JsonLinesByPolars",
    "JsonLinesByPySpark",
    "MarkdownByPython",
    "PandasEngine",
    "PandasOptions",
    "ParquetByPandas",
    "ParquetByPolars",
    "ParquetByPySpark",
    "PillowEngine",
    "PolarsEngine",
    "PolarsOptions",
    "PySparkEngine",
    "TextByPython",
]
