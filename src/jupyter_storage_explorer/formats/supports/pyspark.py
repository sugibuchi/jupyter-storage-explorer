"""Load code with Spark (PySpark). Spark reads with its own storage
configuration, so the code gets no storage options; URLs are rewritten as
Spark reads them (``spark_url``)."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import format_kwargs, spark_url
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.requirements import DeltaSpark, PySpark
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, JsonLines

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import Target


class CsvByPySpark(FormatSupport):
    format = Csv
    use = PySpark
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.csv({url}, header=True, inferSchema=True{kwargs})
        """)

    def recipe(self, fmt: Csv, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(spark_url(target.url)),
            kwargs=format_kwargs(sep=fmt.code_separator(target)),
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

    def recipe(self, fmt: JsonLines, target: Target) -> str:
        return self.recipe_template.format(url=repr(spark_url(target.url)))


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

    def recipe(self, fmt: Parquet, target: Target) -> str:
        return self.recipe_template.format(url=repr(spark_url(target.url)))


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

    def recipe(self, fmt: DeltaLake, target: Target) -> str:
        return self.recipe_template.format(url=repr(spark_url(target.url)))
