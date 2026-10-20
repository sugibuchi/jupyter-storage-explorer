"""Load code with Spark (PySpark). Spark reads with its own storage
configuration, so the code gets no storage options; URLs are rewritten as
Spark reads them (``spark_url``)."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import format_kwargs
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.packages import DeltaSpark, PySpark
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, JsonLines

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.support import SupportOptions

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


AS_DATA_FRAME = "Load as DataFrame"


class CsvByPySpark(FormatSupport):
    format = Csv
    engine = PySpark
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.csv({url}, header=True, inferSchema=True{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(spark_url(ctx.location.url)),
                kwargs=format_kwargs(sep=fmt.code_separator(ctx.fs, ctx.path)),
            )
        }


class JsonLinesByPySpark(FormatSupport):
    format = JsonLines
    engine = PySpark
    capabilities = ("recipe",)

    # Spark reads JSON Lines (one record per line) by default.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.json({url})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(spark_url(ctx.location.url))
            )
        }


class ParquetByPySpark(FormatSupport):
    format = Parquet
    engine = PySpark
    capabilities = ("recipe",)

    # A file or a folder of them; Spark finds partitions itself.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.parquet({url})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(spark_url(ctx.location.url))
            )
        }


class DeltaLakeByPySpark(FormatSupport):
    format = DeltaLake
    engine = PySpark
    # Delta Lake set up in the Spark session (on Databricks, it is).
    additional_requirements = (DeltaSpark,)
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        # Needs Delta Lake in the Spark session (Databricks has it)
        spark = SparkSession.builder.getOrCreate()
        df = spark.read.format("delta").load({url})
        """)

    def recipe(
        self, fmt: DeltaLake, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(spark_url(ctx.location.url))
            )
        }
