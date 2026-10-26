"""Delta Lake tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import DataFormat

if TYPE_CHECKING:
    from jupyter_storage_explorer.base import ItemContext


class DeltaLake(DataFormat):
    name = "delta"
    label = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files

    def matches(self, ctx: ItemContext) -> bool:
        return ctx.is_dir and "_delta_log" in ctx.child_names
