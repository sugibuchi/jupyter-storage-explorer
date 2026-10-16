"""Table sections from DataFrames loaded by library previews.

Duck-typed, so neither polars nor pandas is imported here.
"""

from __future__ import annotations

from typing import Any

from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer.formats.base import TablePreview


def rows_note(
    count: int, more: bool, unit: str = "rows", total: int | None = None
) -> str:
    if not more:
        return f"{count:,} {unit}"
    return (
        f"First {count:,} of {total:,} {unit}"
        if total is not None
        else f"First {count:,} {unit}"
    )


def polars_table(df: Any, **kwargs: Any) -> TablePreview:
    return TablePreview(
        columns=list(df.columns),
        rows=[[jsonable(v) for v in row] for row in df.rows()],
        dtypes=[str(t) for t in df.dtypes],
        **kwargs,
    )


def pandas_table(df: Any, **kwargs: Any) -> TablePreview:
    # Object dtype makes NaN/NaT/NA replaceable with None.
    cells = df.astype(object).where(df.notna(), None)
    return TablePreview(
        columns=[str(c) for c in df.columns],
        rows=[[jsonable(v) for v in row] for row in cells.itertuples(index=False)],
        dtypes=[str(t) for t in df.dtypes],
        **kwargs,
    )
