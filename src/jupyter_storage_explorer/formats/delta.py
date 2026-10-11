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
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.frames import polars_table, rows_note
from jupyter_storage_explorer.formats.requirements import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.requirements import DeltaSpark, Polars

if TYPE_CHECKING:
    from collections.abc import Mapping


class DeltaLake(DataFormat):
    name = "delta"
    label = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files
    preferred_requirements = ((Polars, DeltaLakePackage),)
    # delta-spark: pyspark with Delta Lake set up in a session it creates.
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

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        if self.installed_requirements() is None:
            return self.install_hint()
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
            # Spark reads with its own storage configuration.
            spark = DeltaSpark()
            code = f'df = {spark.code_name()}.read.format("delta").load({format_args(spark_url(target.url))})'
            # Without a session in the notebook, the recipe's setup part creates
            # one with Delta Lake; the notebook's own must have it set up.
            if spark.get_module_name() is None:
                return code
            return (
                f"# Needs Delta Lake in the Spark session (Databricks has it)\n{code}"
            )
        # Only the arguments that differ from scan_delta's defaults.
        kwargs: dict[str, Any] = {}
        if storage_options := snippet_options(self.polars_storage_options):
            kwargs["storage_options"] = storage_options
        if self.polars_delta_table_options is not None:
            kwargs["delta_table_options"] = self.polars_delta_table_options
        if self.polars_delta_use_pyarrow:
            kwargs["use_pyarrow"] = True
        if self.polars_delta_pyarrow_options is not None:
            kwargs["pyarrow_options"] = self.polars_delta_pyarrow_options
        return f"df = {Polars().code_name()}.scan_delta({format_args(target.url, **kwargs)})"
