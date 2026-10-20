"""Delta Lake tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import DataFormat, child_names

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.location import Location


class DeltaLake(DataFormat):
    name = "delta"
    label = "Delta Lake table"
    priority = 20  # a Delta table is also a directory of Parquet files

    def matches(
        self,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        info: Mapping[str, Any],
        children: Sequence[Mapping[str, Any]] | None,
    ) -> bool:
        return children is not None and "_delta_log" in child_names(children)
