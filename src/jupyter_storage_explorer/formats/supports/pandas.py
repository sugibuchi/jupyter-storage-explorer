"""Formats handled with pandas: views of their first rows, and load code."""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    head_text,
    library_url,
    read_whole,
)
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.frames import rows_note, with_sheets
from jupyter_storage_explorer.formats.packages import Openpyxl, Pandas, PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    FormatSupport,
    SupportOptions,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import TableView

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits

AS_DATA_FRAME = "Load as DataFrame"
# Data files read for a directory's view: enough for the first rows.
_VIEW_FILES = 10


def _table(df: Any, **kwargs: Any) -> TableView:
    """A pandas DataFrame as a table view."""
    # Object dtype makes NaN/NaT/NA replaceable with None.
    cells = df.astype(object).where(df.notna(), None)
    return TableView(
        columns=[str(c) for c in df.columns],
        rows=[[jsonable(v) for v in row] for row in cells.itertuples(index=False)],
        dtypes=[str(t) for t in df.dtypes],
        **kwargs,
    )


@dataclass(frozen=True, kw_only=True)
class PandasOptions(SupportOptions):
    """The options of the formats pandas reads.

    Attributes
    ----------
    storage_options : mapping or None, default None
        pandas' (fsspec's) ``storage_options`` in the code; those that look
        like credentials are left out. Views read through the explorer's
        filesystem.
    """

    storage_options: Mapping[str, Any] | None = secret_dict_field(
        default=None,
        secret_keys=[
            "account_key",
            "sas_token",
            "connection_string",
            "client_secret",
            "key",
            "secret",
            "token",
            "password",
        ],
    )


class _PandasByUrl(FormatSupport):
    """A format whose code pandas reads by URL, with storage options."""

    engine = Pandas
    options_model = PandasOptions


class CsvByPandas(_PandasByUrl):
    format = Csv
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Csv, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        pd = Pandas().load()
        text, truncated = head_text(ctx.fs, ctx.path, limits.max_bytes)
        df = pd.read_csv(
            io.StringIO(text),
            sep=fmt.separator(ctx.name, text),
            nrows=limits.max_display_rows,
        )
        more = truncated or len(df) == limits.max_display_rows
        return _table(df, note=rows_note(len(df), more))

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_csv({url}{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(ctx.location)),
                kwargs=format_kwargs(
                    sep=fmt.code_separator(ctx.fs, ctx.path),
                    storage_options=options.code_value("storage_options"),
                ),
            )
        }


class JsonLinesByPandas(_PandasByUrl):
    format = JsonLines
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: PandasOptions,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        text, truncated = head_text(ctx.fs, ctx.path, limits.max_bytes)
        df = pd.read_json(io.StringIO(text), lines=True, nrows=limits.max_display_rows)
        more = truncated or len(df) == limits.max_display_rows
        return _table(df, note=rows_note(len(df), more, "records"))

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}, lines=True{kwargs})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(ctx.location)),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }


class JsonByPandas(_PandasByUrl):
    """Load code only: JSON is viewed as a tree (``JsonByPython``)."""

    format = Json
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}{kwargs})
        """)

    def recipe(
        self, fmt: Json, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(ctx.location)),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }


class ExcelByPandas(_PandasByUrl):
    format = Excel
    additional_requirements = (Openpyxl,)  # pandas' Excel engine
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Excel, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        pd = Pandas().load()
        workbook = pd.ExcelFile(
            io.BytesIO(read_whole(ctx.fs, ctx.path, limits)), engine="openpyxl"
        )
        name = workbook.sheet_names[0]
        # One extra row tells whether there are more.
        df = workbook.parse(name, nrows=limits.max_display_rows + 1)
        note = rows_note(
            min(len(df), limits.max_display_rows), len(df) > limits.max_display_rows
        )
        return _table(
            df.head(limits.max_display_rows),
            title=name,
            note=with_sheets(note, workbook.sheet_names),
        )

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_excel({url}{kwargs})
        """)

    def recipe(
        self, fmt: Excel, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(ctx.location)),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }


class ParquetByPandas(_PandasByUrl):
    format = Parquet
    additional_requirements = (PyArrow,)  # pandas' Parquet engine
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Parquet, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        pa_dataset = PyArrow().load("dataset")
        # pyarrow reads through the browser's fsspec filesystem, so any storage
        # works. For a directory, given its first few files, of one partition
        # if it is partitioned (with its columns from the folders' names):
        # pyarrow would otherwise search all subdirectories.
        options: dict[str, Any] = {}
        if not ctx.is_dir:
            source: Any = ctx.path
        else:
            source = fmt.first_files(ctx, _VIEW_FILES)
            if fmt.layout(ctx).keys:
                options = {"partitioning": "hive", "partition_base_dir": ctx.path}
        if not source:
            raise ValueError("no Parquet files found")
        dataset = pa_dataset.dataset(
            source, filesystem=ctx.fs, format="parquet", **options
        )
        df = dataset.head(limits.max_display_rows).to_pandas()
        if ctx.is_dir:
            note = rows_note(len(df), len(df) == limits.max_display_rows)
        else:
            total = dataset.count_rows()
            note = rows_note(len(df), len(df) < total, total=total)
        return _table(df, note=note)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_parquet({url}{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(ctx.location)),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }
