"""Delta Lake tables."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.format import DataFormat, Target
from jupyter_storage_explorer.formats.frames import polars_table, rows_note
from jupyter_storage_explorer.formats.requirements import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.requirements import DeltaSpark, Polars

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits
    from jupyter_storage_explorer.formats.requirement import Requirements


class DeltaLake(DataFormat):
    name = "delta"
    label = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files
    preferred_requirements = ((Polars, DeltaLakePackage),)
    # delta-spark: a Spark session with Delta Lake set up.
    code_only_requirements = ((DeltaSpark,),)
    query_requirements = (Polars, DeltaLakePackage)

    def __init__(
        self,
        *,
        polars_storage_options: Mapping[str, Any] | None = None,
        polars_credential_provider: Any = "auto",
        polars_delta_table_options: Mapping[str, Any] | None = None,
        polars_delta_use_pyarrow: bool = False,
        polars_delta_pyarrow_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Options of polars' ``scan_delta``, for the preview, the data browser
        and the polars code snippet: ``storage_options`` and
        ``credential_provider``, shared with the other formats polars reads,
        and ``delta_table_options``, ``use_pyarrow`` and ``pyarrow_options``.

        ``polars_storage_options`` are delta-rs' (object_store's), not
        fsspec's; without them, credentials come from the environment. In the
        snippet, ones that look like credentials are left out, as is the
        credential provider. Other options (``kwargs``) are ignored.
        """
        self.polars_storage_options = polars_storage_options
        self.polars_credential_provider = polars_credential_provider
        self.polars_delta_table_options = polars_delta_table_options
        self.polars_delta_use_pyarrow = polars_delta_use_pyarrow
        self.polars_delta_pyarrow_options = polars_delta_pyarrow_options

    def matches(self, target: Target) -> bool:
        return target.is_dir and "_delta_log" in target.child_names

    def scan(self, url: str, is_dir: bool) -> Any:
        # polars reads the table with deltalake (delta-rs), which reads cloud
        # storage itself, by default with credentials from the environment.
        return (
            Polars()
            .load()
            .scan_delta(
                url,
                storage_options=self.polars_storage_options,
                credential_provider=self.polars_credential_provider,
                delta_table_options=self.polars_delta_table_options,
                use_pyarrow=self.polars_delta_use_pyarrow,
                pyarrow_options=self.polars_delta_pyarrow_options,
            )
        )

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        return self.preview_with_polars(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        df = self.scan(target.url, target.is_dir).head(limits.max_rows).collect()
        return [
            polars_table(df, note=rows_note(df.height, df.height == limits.max_rows))
        ]

    def load_code(self, target: Target, requirements: Requirements) -> str:
        if DeltaSpark in requirements:
            return self.load_code_delta_spark(target)
        return self.load_code_polars(target)

    load_code_polars_template = cleandoc("""
        import polars as pl

        df = pl.scan_delta({url}{kwargs})
        """)

    def load_code_polars(self, target: Target) -> str:
        # Only the arguments that differ from scan_delta's defaults.
        return self.load_code_polars_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=snippet_options(self.polars_storage_options) or None,
                delta_table_options=self.polars_delta_table_options,
                use_pyarrow=True if self.polars_delta_use_pyarrow else None,
                pyarrow_options=self.polars_delta_pyarrow_options,
            ),
        )

    load_code_delta_spark_template = cleandoc("""
        from pyspark.sql import SparkSession

        # Needs Delta Lake in the Spark session (Databricks has it)
        spark = SparkSession.builder.getOrCreate()
        df = spark.read.format("delta").load({url})
        """)

    def load_code_delta_spark(self, target: Target) -> str:
        # Spark reads with its own storage configuration.
        return self.load_code_delta_spark_template.format(
            url=repr(spark_url(target.url))
        )
