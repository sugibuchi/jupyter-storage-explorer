"""Excel workbooks (.xlsx)."""

from __future__ import annotations

import io
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import format_kwargs, snippet_options
from jupyter_storage_explorer.formats.format import DataFormat, Target
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

    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits
    from jupyter_storage_explorer.formats.requirement import Requirements


def _with_sheets(note: str, sheets: list[str]) -> str:
    """The note under the first sheet's table, mentioning the other sheets."""
    return f"{note}; other sheets: {', '.join(sheets[1:])}" if len(sheets) > 1 else note


class Excel(DataFormat):
    name = "excel"
    label = "Excel workbook"
    extensions = (".xlsx", ".xlsm")
    file_icon = "spreadsheet"
    # polars reads Excel from bytes, fetched with fsspec so any storage works.
    preferred_requirements = ((Polars, Fastexcel, Fsspec), (Pandas, Openpyxl))
    query_requirements = (Polars, Fastexcel)

    def __init__(
        self,
        *,
        fsspec_storage_options: Mapping[str, Any] | None = None,
        pandas_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the polars snippet, which reads the bytes with it.
        ``pandas_storage_options``: for pandas' ``read_excel`` in the pandas
        snippet.

        Storage options that look like credentials are left out. Other
        options (``kwargs``) are ignored.
        """
        self.fsspec_storage_options = fsspec_storage_options
        self.pandas_storage_options = pandas_storage_options

    def scan(self, url: str, is_dir: bool) -> Any:
        # Excel cannot be read lazily: the first sheet is read whole and
        # queried in memory.
        return Polars().load().read_excel(url).lazy()

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

    def load_code(self, target: Target, requirements: Requirements) -> str:
        if Polars in requirements:
            return self.load_code_polars(target)
        return self.load_code_pandas(target)

    # polars reads the bytes, fetched with fsspec so any storage works.
    load_code_polars_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            df = pl.read_excel(f.read())
        """)

    def load_code_polars(self, target: Target) -> str:
        return self.load_code_polars_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(**snippet_options(self.fsspec_storage_options)),
        )

    load_code_pandas_template = cleandoc("""
        import pandas as pd

        df = pd.read_excel({url}{kwargs})
        """)

    def load_code_pandas(self, target: Target) -> str:
        return self.load_code_pandas_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=snippet_options(self.pandas_storage_options) or None
            ),
        )
