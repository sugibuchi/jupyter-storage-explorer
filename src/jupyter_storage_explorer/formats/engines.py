"""The predefined engines (``Engine`` subclasses, see engine.py) of the
predefined supports."""

from __future__ import annotations

from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.packages import (
    DatabricksConnect,
    Fsspec,
    Pandas,
    Pillow,
    Polars,
    PySpark,
)


class PolarsEngine(Engine):
    key = "polars"
    label = "Polars"
    requirements = (Polars(),)


class PandasEngine(Engine):
    key = "pandas"
    label = "pandas"
    requirements = (Pandas(),)


class PySparkEngine(Engine):
    """Spark's Python API, with pyspark or with Databricks Connect."""

    key = "pyspark"
    label = "PySpark"
    requirements = ((PySpark(),), (DatabricksConnect(),))


class FsspecEngine(Engine):
    """Files read with fsspec: code only (text, JSON values)."""

    key = "fsspec"
    label = "fsspec"
    requirements = (Fsspec(),)


class PillowEngine(Engine):
    """Images opened with Pillow: code only (the browser shows images itself)."""

    key = "pillow"
    label = "Pillow"
    requirements = (Pillow(),)
