"""Load code with Spark (PySpark). Spark reads with its own storage
configuration, so the code gets no storage options; URLs are rewritten as
Spark reads them (``spark_url``)."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import format_kwargs
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.requirements import DeltaSpark, PySpark
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, JsonLines

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.location import Location


# Spark (Hadoop) names for storage URLs: TLS "abfss" for Azure, as Spark
# expects it (storage accounts usually require secure transfer); "s3a", the
# S3 connector of open-source Hadoop (Databricks and EMR accept it too).
_SPARK_SCHEMES = {"abfs": "abfss", "az": "abfss", "s3": "s3a"}


def spark_url(url: str) -> str:
    """``url`` as Spark reads it, e.g. "abfss://c@a.dfs.core.windows.net/x" for
    "abfs://c@a.dfs.core.windows.net/x" or "s3a://bucket/x" for "s3://bucket/x".

    Other URLs and local paths are unchanged.
    """
    scheme, sep, rest = url.partition("://")
    return (
        f"{_SPARK_SCHEMES[scheme]}://{rest}"
        if sep and scheme in _SPARK_SCHEMES
        else url
    )


class CsvByPySpark(FormatSupport):
    format = Csv
    use = PySpark
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.csv({url}, header=True, inferSchema=True{kwargs})
        """)

    def recipe(
        self,
        fmt: Csv,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        return self.recipe_template.format(
            url=repr(spark_url(location.url)),
            kwargs=format_kwargs(sep=fmt.code_separator(fs, path)),
        )


class JsonLinesByPySpark(FormatSupport):
    format = JsonLines
    use = PySpark
    capabilities = ("recipe",)

    # Spark reads JSON Lines (one record per line) by default.
    recipe_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.json({url})
        """)

    def recipe(
        self,
        fmt: JsonLines,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        return self.recipe_template.format(url=repr(spark_url(location.url)))


class ParquetByPySpark(FormatSupport):
    format = Parquet
    use = PySpark
    capabilities = ("recipe",)

    # A file or a folder of them; Spark finds partitions itself.
    recipe_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.parquet({url})
        """)

    def recipe(
        self,
        fmt: Parquet,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        return self.recipe_template.format(url=repr(spark_url(location.url)))


class DeltaLakeByPySpark(FormatSupport):
    format = DeltaLake
    use = PySpark
    # Delta Lake set up in the Spark session (on Databricks, it is).
    additional_requirements = (DeltaSpark,)
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        from pyspark.sql import SparkSession

        # Needs Delta Lake in the Spark session (Databricks has it)
        spark = SparkSession.builder.getOrCreate()
        df = spark.read.format("delta").load({url})
        """)

    def recipe(
        self,
        fmt: DeltaLake,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        return self.recipe_template.format(url=repr(spark_url(location.url)))
