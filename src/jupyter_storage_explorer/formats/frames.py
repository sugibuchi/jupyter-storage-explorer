"""The notes under table previews, shared by the libraries' supports (their
tables are made in their modules: supports/polars.py, supports/pandas.py)."""

from __future__ import annotations


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


def with_sheets(note: str, sheets: list[str]) -> str:
    """The note under a workbook's first sheet's table, mentioning the other sheets."""
    return f"{note}; other sheets: {', '.join(sheets[1:])}" if len(sheets) > 1 else note
