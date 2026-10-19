"""The predefined packages used by previews and the generated load code
(``Requirement`` subclasses, see requirement.py)."""

from __future__ import annotations

from jupyter_storage_explorer.formats.requirement import Requirement


class Fsspec(Requirement):
    package = "fsspec"
    import_name = "fsspec"


class Polars(Requirement):
    package = "polars"
    import_name = "polars"


class Pandas(Requirement):
    package = "pandas"
    import_name = "pandas"


class Pillow(Requirement):
    package = "pillow"
    import_name = "PIL"


class PySpark(Requirement):
    """Spark, used only in load code (``DataFormat.code_requirements``)."""

    package = "pyspark"
    import_name = "pyspark"


class DeltaSpark(PySpark):
    """Delta Lake for Spark: like ``PySpark``, with Delta Lake set up in the
    session (on Databricks, it is)."""

    package = "delta-spark"
    import_name = "delta"


# Optional dependencies of the packages above: installed, never imported by snippets.


class PyArrow(Requirement):
    """Parquet engine for pandas."""

    package = "pyarrow"
    import_name = "pyarrow"


class DeltaLake(Requirement):
    """Delta Lake reader used by ``pl.read_delta``."""

    package = "deltalake"
    import_name = "deltalake"


class Openpyxl(Requirement):
    """Excel engine for pandas."""

    package = "openpyxl"
    import_name = "openpyxl"


class Fastexcel(Requirement):
    """Excel engine for polars."""

    package = "fastexcel"
    import_name = "fastexcel"
