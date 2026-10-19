"""Delta Lake tables."""

from __future__ import annotations

from jupyter_storage_explorer.formats.format import DataFormat, Target


class DeltaLake(DataFormat):
    name = "delta"
    label = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files

    def matches(self, target: Target) -> bool:
        return target.is_dir and "_delta_log" in target.child_names
