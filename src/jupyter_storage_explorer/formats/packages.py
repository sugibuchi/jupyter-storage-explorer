"""The predefined packages the supports use (``PythonPackage`` subclasses, see
package.py)."""

from __future__ import annotations

from jupyter_storage_explorer.formats.package import PythonPackage


class Fsspec(PythonPackage):
    package = "fsspec"
    import_name = "fsspec"


class Polars(PythonPackage):
    package = "polars"
    import_name = "polars"


class Pandas(PythonPackage):
    package = "pandas"
    import_name = "pandas"


class Pillow(PythonPackage):
    package = "pillow"
    import_name = "PIL"


class PySpark(PythonPackage):
    """Spark, used only in load code."""

    package = "pyspark"
    import_name = "pyspark"


class DatabricksConnect(PythonPackage):
    """Spark sessions on a Databricks cluster: PySpark's API without pyspark
    itself, an alternative of ``PySparkEngine``."""

    package = "databricks-connect"
    # "databricks" alone is a namespace other packages share (databricks-sdk).
    import_name = "databricks.connect"


# Optional dependencies of the packages above: installed, never imported by snippets.


class DeltaSpark(PythonPackage):
    """Delta Lake for Spark, set up in the session (on Databricks, it is)."""

    package = "delta-spark"
    import_name = "delta"


class PyArrow(PythonPackage):
    """Parquet engine for pandas."""

    package = "pyarrow"
    import_name = "pyarrow"


class DeltaLake(PythonPackage):
    """Delta Lake reader used by ``pl.read_delta``."""

    package = "deltalake"
    import_name = "deltalake"


class Openpyxl(PythonPackage):
    """Excel engine for pandas."""

    package = "openpyxl"
    import_name = "openpyxl"


class Fastexcel(PythonPackage):
    """Excel engine for polars."""

    package = "fastexcel"
    import_name = "fastexcel"
