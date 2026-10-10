"""Packages used by previews and the generated load snippets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import Requirement, _user_namespace

if TYPE_CHECKING:
    from collections.abc import Mapping


class Fsspec(Requirement):
    package = "fsspec"
    import_name = "fsspec"
    preferred_names = ("fsspec",)


class Polars(Requirement):
    package = "polars"
    import_name = "polars"
    preferred_names = ("pl", "polars")


class Pandas(Requirement):
    package = "pandas"
    import_name = "pandas"
    preferred_names = ("pd", "pandas")


class Pillow(Requirement):
    package = "pillow"
    import_name = "PIL"
    preferred_names = ("PIL",)

    @property
    def import_command(self) -> str:
        # ``import PIL`` alone does not load the PIL.Image submodule the code uses.
        return "import PIL.Image"


class PySpark(Requirement):
    """Spark, used only in load code (``DataFormat.code_only_requirements``).

    Code reads with a SparkSession named ``spark``, as notebooks on Spark
    platforms (e.g. Databricks) already have; when missing, the recipe's
    setup part (with the install lines) creates it.
    """

    package = "pyspark"
    import_name = "pyspark"
    preferred_names = ("spark",)

    @property
    def import_command(self) -> None:
        return None  # the load code uses the session, set up by setup_command

    @property
    def setup_command(self) -> str:
        return "from pyspark.sql import SparkSession\n\nspark = SparkSession.builder.getOrCreate()"

    def get_module_name(self, namespace: Mapping[str, Any] | None = None) -> str | None:
        """The name ``spark`` if the notebook has a SparkSession so named, else None."""
        if namespace is None:
            namespace = _user_namespace()
        session = namespace.get("spark")
        # Checked by type name, so pyspark is not imported just to look.
        cls = type(session)
        if cls.__name__ == "SparkSession" and cls.__module__.startswith("pyspark."):
            return "spark"
        return None


class DeltaSpark(PySpark):
    """Delta Lake for Spark: like ``PySpark``, but a session it creates has
    Delta Lake set up. Installing it installs a matching pyspark too.

    A notebook's existing ``spark`` session is used as is (on Databricks, it
    has Delta Lake).
    """

    package = "delta-spark"
    import_name = "delta"

    @property
    def setup_command(self) -> str:
        # As in Delta Lake's quickstart for pip installs.
        return (
            "from delta import configure_spark_with_delta_pip\n"
            "from pyspark.sql import SparkSession\n"
            "\n"
            "builder = (\n"
            "    SparkSession.builder\n"
            '    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")\n'
            '    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")\n'
            ")\n"
            "spark = configure_spark_with_delta_pip(builder).getOrCreate()"
        )


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
