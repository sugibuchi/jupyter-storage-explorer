"""Formats handled with Spark (PySpark): the data browser, on a Spark
DataFrame (lazy: each page a Spark job), and load code. Spark reads with its
own storage configuration (``PySparkOptions.session_options``), and reads the
item's URL, rewritten as Spark reads it (``spark_url``): the explorer's
filesystem is not used, and storages Spark cannot reach (e.g. fsspec's
memory filesystem) cannot be viewed."""

from __future__ import annotations

from dataclasses import dataclass
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
from jupyter_storage_explorer.formats.support import (
    FormatSupport,
    SupportOptions,
    format_kwargs,
)
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.view import QueryView

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext
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


def spark_session(session_options: Mapping[str, Any] | None = None) -> Any:
    """The Spark session views read with: the active one (e.g. the
    notebook's on Databricks, or one the user created in the kernel), else
    one created, by Databricks Connect if it is installed (its own pyspark
    needs it), else by pyspark.

    ``session_options`` are given to the session's builder (``config(key,
    value)``); with a session already running, ``getOrCreate`` returns it,
    applying those Spark can still change (runtime configuration). A builder
    without ``config`` (some Databricks Connect versions) gets them as the
    session's runtime configuration (``spark.conf.set``) instead."""
    spark_session_class = PySpark().load("sql").SparkSession
    active = spark_session_class.getActiveSession()
    if active is not None and not session_options:
        return active
    if active is None and DatabricksConnect().is_installed():
        builder = DatabricksConnect().load().DatabricksSession.builder
    else:
        builder = spark_session_class.builder
    config = dict(session_options or {})
    if not hasattr(builder, "config"):
        session = builder.getOrCreate()
        for key, value in config.items():
            session.conf.set(key, value)
        return session
    for key, value in config.items():
        builder = builder.config(key, value)
    return builder.getOrCreate()


def _url(ctx: ItemContext) -> str:
    return spark_url(ctx.location.url)


class PySparkEngine(Engine):
    """Spark's Python API, with pyspark or with Databricks Connect."""

    key = "pyspark"
    label = "PySpark"
    requirements = ((PySpark(),), (DatabricksConnect(),))


@dataclass(frozen=True, kw_only=True)
class PySparkOptions(SupportOptions):
    """The options of the formats Spark reads, for the data browser and the
    code.

    Attributes
    ----------
    session_options : mapping or None, default None
        Spark configuration given to ``SparkSession.builder.config(key,
        value)``, e.g. Delta Lake's ``{"spark.sql.extensions":
        "io.delta.sql.DeltaSparkSessionExtension", ...}`` or storage access
        (``"spark.hadoop.fs.azure.account.key.<account>.dfs.core.windows.net"``).
        With a session already running, only what Spark can change at run time
        applies. In the code, those that look like credentials are left out.
    reader_options : mapping or None, default None
        Options given to the reader, ``spark.read.option(key, value)``, e.g.
        ``{"mode": "DROPMALFORMED"}``; for CSV, they override the defaults
        ``header``, ``inferSchema`` and the separator detected (``sep``).
    """

    session_options: Mapping[str, Any] | None = None
    reader_options: Mapping[str, Any] | None = None

    def reader(self, spark: Any, defaults: Mapping[str, Any] | None = None) -> Any:
        """``spark.read`` with ``defaults``, then ``reader_options``, which
        override them."""
        reader = spark.read
        for key, value in {**(defaults or {}), **(self.reader_options or {})}.items():
            reader = reader.option(key, value)
        return reader

    def session_code(self) -> str:
        """The code's line creating the session, with ``session_options``
        (those fit to show)."""
        config = self.code_value("session_options") or {}
        if not config:
            return "spark = SparkSession.builder.getOrCreate()"
        lines = [f"    .config({key!r}, {value!r})" for key, value in config.items()]
        return "\n".join(
            ["spark = (", "    SparkSession.builder", *lines, "    .getOrCreate()", ")"]
        )

    def reader_code(self) -> str:
        """What follows ``spark.read`` in the code: an ``.option(key, value)``
        per reader option (those fit to show)."""
        reader = self.code_value("reader_options") or {}
        return "".join(f".option({key!r}, {value!r})" for key, value in reader.items())


class _BySpark(FormatSupport):
    """A format Spark reads, with its session and reader options."""

    engine = PySparkEngine
    options_model = PySparkOptions


AS_DATA_FRAME = "Load as DataFrame"


class CsvByPySpark(_BySpark):
    format = Csv
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Csv, ctx: ItemContext, options: PySparkOptions, limits: ViewLimits
    ) -> View:
        # The separator from the beginning, read through the explorer.
        text, _ = ctx.head_text(limits.max_bytes)
        defaults = {
            "header": True,
            "inferSchema": True,
            "sep": fmt.separator(ctx.name, text),
        }
        spark = spark_session(options.session_options)
        return QueryView(data=options.reader(spark, defaults).csv(_url(ctx)))

    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        {session}
        df = spark.read{reader}.csv({url}{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: PySparkOptions
    ) -> dict[str, str]:
        # The defaults, but those the reader options override.
        overridden = set(options.reader_options or {})
        defaults = {"header": True, "inferSchema": True, "sep": fmt.code_separator(ctx)}
        kwargs = {k: v for k, v in defaults.items() if k not in overridden}
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                session=options.session_code(),
                reader=options.reader_code(),
                url=repr(_url(ctx)),
                kwargs=format_kwargs(**kwargs),
            )
        }


class JsonLinesByPySpark(_BySpark):
    format = JsonLines
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: PySparkOptions,
        limits: ViewLimits,
    ) -> View:
        spark = spark_session(options.session_options)
        return QueryView(data=options.reader(spark).json(_url(ctx)))

    # Spark reads JSON Lines (one record per line) by default.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        {session}
        df = spark.read{reader}.json({url})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: PySparkOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            session=options.session_code(),
            reader=options.reader_code(),
            url=repr(_url(ctx)),
        )
        return {AS_DATA_FRAME: code}


class ParquetByPySpark(_BySpark):
    format = Parquet
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: PySparkOptions,
        limits: ViewLimits,
    ) -> View:
        # A file or a folder of them; Spark finds partitions itself.
        spark = spark_session(options.session_options)
        return QueryView(data=options.reader(spark).parquet(_url(ctx)))

    # A file or a folder of them; Spark finds partitions itself.
    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        {session}
        df = spark.read{reader}.parquet({url})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: PySparkOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            session=options.session_code(),
            reader=options.reader_code(),
            url=repr(_url(ctx)),
        )
        return {AS_DATA_FRAME: code}


class DeltaLakeByPySpark(_BySpark):
    format = DeltaLake
    # Delta Lake set up in the Spark session (on Databricks, it is).
    additional_requirements = (DeltaSpark(),)
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: DeltaLake,
        ctx: ItemContext,
        options: PySparkOptions,
        limits: ViewLimits,
    ) -> View:
        spark = spark_session(options.session_options)
        data = options.reader(spark).format("delta").load(_url(ctx))
        return QueryView(data=data)

    data_frame_template = cleandoc("""
        from pyspark.sql import SparkSession

        # Needs Delta Lake in the Spark session (Databricks has it)
        {session}
        df = spark.read{reader}.format("delta").load({url})
        """)

    def recipe(
        self, fmt: DeltaLake, ctx: ItemContext, options: PySparkOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            session=options.session_code(),
            reader=options.reader_code(),
            url=repr(_url(ctx)),
        )
        return {AS_DATA_FRAME: code}
