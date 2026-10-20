"""Formats handled with Spark (PySpark): the data browser, on a Spark
DataFrame (lazy: each page a Spark job), and load code. Spark reads with its
own storage configuration, so neither gets storage options, and reads the
item's URL, rewritten as Spark reads it (``spark_url``): the explorer's
filesystem is not used, and storages Spark cannot reach (e.g. fsspec's
memory filesystem) cannot be viewed."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.packages import (
    DatabricksConnect,
    DeltaSpark,
    PySpark,
)
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import FormatSupport, format_kwargs
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.view import QueryView

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.support import SupportOptions
    from jupyter_storage_explorer.formats.view import View, ViewLimits

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


def spark_session() -> Any:
    """The Spark session views read with: the active one (e.g. the
    notebook's on Databricks, or one the user created in the kernel), else
    one created with the default configuration, by Databricks Connect if it
    is installed (its own pyspark needs it), else by pyspark."""
    spark_session_class = PySpark().load("sql").SparkSession
    active = spark_session_class.getActiveSession()
    if active is not None:
        return active
    if DatabricksConnect().is_installed():
        return DatabricksConnect().load().DatabricksSession.builder.getOrCreate()
    return spark_session_class.builder.getOrCreate()


def _url(ctx: ItemContext) -> str:
    return spark_url(ctx.location.url)


AS_DATA_FRAME = "Load as DataFrame"


class PySparkEngine(Engine):
    """Spark's Python API, with pyspark or with Databricks Connect."""

    key = "pyspark"
    label = "PySpark"
    requirements = ((PySpark(),), (DatabricksConnect(),))


class CsvByPySpark(FormatSupport):
    format = Csv
    engine = PySparkEngine
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Csv, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
    ) -> View:
        # The separator from the beginning, read through the explorer.
        text, _ = ctx.head_text(limits.max_bytes)
        data = spark_session().read.csv(
            _url(ctx),
            header=True,
            inferSchema=True,
            sep=fmt.separator(ctx.name, text),
        )
        return QueryView(data=data)

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
                url=repr(_url(ctx)),
                kwargs=format_kwargs(sep=fmt.code_separator(ctx)),
            )
        }


class JsonLinesByPySpark(FormatSupport):
    format = JsonLines
    engine = PySparkEngine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: SupportOptions,
        limits: ViewLimits,
    ) -> View:
        return QueryView(data=spark_session().read.json(_url(ctx)))

    # Spark reads JSON Lines (one record per line) by default.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.json({url})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {AS_DATA_FRAME: self.data_frame_template.format(url=repr(_url(ctx)))}


class ParquetByPySpark(FormatSupport):
    format = Parquet
    engine = PySparkEngine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: SupportOptions,
        limits: ViewLimits,
    ) -> View:
        # A file or a folder of them; Spark finds partitions itself.
        return QueryView(data=spark_session().read.parquet(_url(ctx)))

    # A file or a folder of them; Spark finds partitions itself.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.parquet({url})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {AS_DATA_FRAME: self.data_frame_template.format(url=repr(_url(ctx)))}


class DeltaLakeByPySpark(FormatSupport):
    format = DeltaLake
    engine = PySparkEngine
    # Delta Lake set up in the Spark session (on Databricks, it is).
    additional_requirements = (DeltaSpark(),)
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: DeltaLake,
        ctx: ItemContext,
        options: SupportOptions,
        limits: ViewLimits,
    ) -> View:
        data = spark_session().read.format("delta").load(_url(ctx))
        return QueryView(data=data)

    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        # Needs Delta Lake in the Spark session (Databricks has it)
        spark = SparkSession.builder.getOrCreate()
        df = spark.read.format("delta").load({url})
        """)

    def recipe(
        self, fmt: DeltaLake, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, str]:
        return {AS_DATA_FRAME: self.data_frame_template.format(url=repr(_url(ctx)))}
