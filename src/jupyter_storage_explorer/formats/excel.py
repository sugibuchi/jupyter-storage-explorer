"""Excel workbooks (.xlsx)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    DataFormat,
    Preview,
    PreviewLimits,
    Requirements,
    Target,
    format_args,
)
from jupyter_storage_explorer.formats.frames import (
    pandas_table,
    polars_table,
    rows_note,
)
from jupyter_storage_explorer.formats.requirements import (
    Fastexcel,
    Fsspec,
    Openpyxl,
    Pandas,
    Polars,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _with_sheets(note: str, sheets: list[str]) -> str:
    """The note under the first sheet's table, mentioning the other sheets."""
    return f"{note}; other sheets: {', '.join(sheets[1:])}" if len(sheets) > 1 else note


class Excel(DataFormat):
    name = "Excel workbook"
    extensions = (".xlsx", ".xlsm")
    # polars reads Excel from bytes, fetched with fsspec so any storage works.
    preferred_requirements = ((Polars, Fastexcel, Fsspec), (Pandas, Openpyxl))

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        requirements = self.installed_requirements()
        if requirements is None:
            return self.install_hint()
        if Polars in requirements:
            return self.preview_with_polars(target, limits)
        return self.preview_with_pandas(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        Polars().load()  # fastexcel's to_polars() needs polars
        fastexcel = Fastexcel().load()
        reader = fastexcel.read_excel(target.read_whole(limits))
        sheet = reader.load_sheet(0, n_rows=limits.max_rows)
        df = sheet.to_polars()
        note = rows_note(
            df.height, sheet.total_height > df.height, total=sheet.total_height
        )
        return [
            polars_table(
                df, title=sheet.name, note=_with_sheets(note, reader.sheet_names)
            )
        ]

    def preview_with_pandas(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pd = Pandas().load()
        workbook = pd.ExcelFile(
            io.BytesIO(target.read_whole(limits)), engine="openpyxl"
        )
        name = workbook.sheet_names[0]
        # One extra row tells whether there are more.
        df = workbook.parse(name, nrows=limits.max_rows + 1)
        note = rows_note(min(len(df), limits.max_rows), len(df) > limits.max_rows)
        return [
            pandas_table(
                df.head(limits.max_rows),
                title=name,
                note=_with_sheets(note, workbook.sheet_names),
            )
        ]

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        if Polars in requirements:
            return (
                f"with {Fsspec().code_name()}.open({format_args(target.url, 'rb', **storage_options)}) as f:\n"
                f"    df = {Polars().code_name()}.read_excel(f.read())"
            )
        options = dict(storage_options) or None
        return f"df = {Pandas().code_name()}.read_excel({format_args(target.url, storage_options=options)})"
