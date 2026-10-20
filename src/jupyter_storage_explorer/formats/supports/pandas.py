"""Formats handled with pandas: views of their first rows, and load code."""

from __future__ import annotations

import io
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._json import jsonable
from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    head_text,
    library_url,
    name_of,
    read_whole,
    snippet_options,
)
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.frames import rows_note, with_sheets
from jupyter_storage_explorer.formats.packages import Openpyxl, Pandas, PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import TableView

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.view import View, ViewLimits
    from jupyter_storage_explorer.location import Location

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


class _PandasByUrl(FormatSupport):
    """A format whose code pandas reads by URL, with storage options."""

    engine = Pandas

    def __init__(self, *, storage_options: Mapping[str, Any] | None = None) -> None:
        """``storage_options``: pandas' (fsspec's) in the code; ones that
        look like credentials are left out."""
        self.storage_options = storage_options

    def code_storage_options(self) -> Mapping[str, Any] | None:
        """The storage options fit to show in code (see ``snippet_options``), or None."""
        return snippet_options(self.storage_options) or None


class CsvByPandas(_PandasByUrl):
    format = Csv
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Csv,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        text, truncated = head_text(fs, path, limits.max_bytes)
        df = pd.read_csv(
            io.StringIO(text),
            sep=fmt.separator(name_of(path), text),
            nrows=limits.max_display_rows,
        )
        more = truncated or len(df) == limits.max_display_rows
        return _table(df, note=rows_note(len(df), more))

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_csv({url}{kwargs})
        """)

    def recipe(
        self,
        fmt: Csv,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(location)),
                kwargs=format_kwargs(
                    sep=fmt.code_separator(fs, path),
                    storage_options=self.code_storage_options(),
                ),
            )
        }


class JsonLinesByPandas(_PandasByUrl):
    format = JsonLines
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        text, truncated = head_text(fs, path, limits.max_bytes)
        df = pd.read_json(io.StringIO(text), lines=True, nrows=limits.max_display_rows)
        more = truncated or len(df) == limits.max_display_rows
        return _table(df, note=rows_note(len(df), more, "records"))

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}, lines=True{kwargs})
        """)

    def recipe(
        self,
        fmt: JsonLines,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(location)),
                kwargs=format_kwargs(storage_options=self.code_storage_options()),
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
        self,
        fmt: Json,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(location)),
                kwargs=format_kwargs(storage_options=self.code_storage_options()),
            )
        }


class ExcelByPandas(_PandasByUrl):
    format = Excel
    additional_requirements = (Openpyxl,)  # pandas' Excel engine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Excel,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        workbook = pd.ExcelFile(
            io.BytesIO(read_whole(fs, path, limits)), engine="openpyxl"
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
        self,
        fmt: Excel,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(location)),
                kwargs=format_kwargs(storage_options=self.code_storage_options()),
            )
        }


class ParquetByPandas(_PandasByUrl):
    format = Parquet
    additional_requirements = (PyArrow,)  # pandas' Parquet engine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Parquet,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        pa_dataset = PyArrow().load("dataset")
        # pyarrow reads through the browser's fsspec filesystem, so any storage
        # works. For a directory, given its first few files, of one partition
        # if it is partitioned (with its columns from the folders' names):
        # pyarrow would otherwise search all subdirectories.
        options: dict[str, Any] = {}
        if not is_dir:
            source: Any = path
        else:
            source = fmt.first_files(location, fs, path, _VIEW_FILES)
            if fmt.layout(location, fs, path).keys:
                options = {"partitioning": "hive", "partition_base_dir": path}
        if not source:
            raise ValueError("no Parquet files found")
        dataset = pa_dataset.dataset(source, filesystem=fs, format="parquet", **options)
        df = dataset.head(limits.max_display_rows).to_pandas()
        if is_dir:
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
        self,
        fmt: Parquet,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(library_url(location)),
                kwargs=format_kwargs(storage_options=self.code_storage_options()),
            )
        }
