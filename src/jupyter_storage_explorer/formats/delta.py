"""Delta Lake tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    DataFormat,
    Preview,
    PreviewLimits,
    Requirements,
    Target,
    format_args,
    spark_url,
)
from jupyter_storage_explorer.formats.frames import polars_table, rows_note
from jupyter_storage_explorer.formats.requirements import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.requirements import DeltaSpark, Polars

if TYPE_CHECKING:
    from collections.abc import Mapping


class DeltaLake(DataFormat):
    name = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files
    preferred_requirements = ((Polars, DeltaLakePackage),)
    # delta-spark: pyspark with Delta Lake set up in a session it creates.
    code_only_requirements = ((DeltaSpark,),)
    query_requirements = (Polars, DeltaLakePackage)

    def matches(self, target: Target) -> bool:
        return target.is_dir and "_delta_log" in target.child_names

    def scan(self, url: str) -> Any:
        # polars reads the table with deltalake (delta-rs), which reads cloud
        # storage itself with credentials from the environment.
        return Polars().load().scan_delta(url)

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        if self.installed_requirements() is None:
            return self.install_hint()
        return self.preview_with_polars(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        df = self.scan(target.url).head(limits.max_rows).collect()
        return [
            polars_table(df, note=rows_note(df.height, df.height == limits.max_rows))
        ]

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        if DeltaSpark in requirements:
            # Spark reads with its own storage configuration, not fsspec's options.
            spark = DeltaSpark()
            code = f'df = {spark.code_name()}.read.format("delta").load({format_args(spark_url(target.url))})'
            # Without a session in the notebook, the recipe's setup part creates
            # one with Delta Lake; the notebook's own must have it set up.
            if spark.get_module_name() is None:
                return code
            return (
                f"# Needs Delta Lake in the Spark session (Databricks has it)\n{code}"
            )
        # delta-rs, not fsspec, reads the table, so its storage options use
        # object_store names (e.g. aws_access_key_id) and may need translating.
        options = dict(storage_options) or None
        return f"df = {Polars().code_name()}.read_delta({format_args(target.url, storage_options=options)})"
