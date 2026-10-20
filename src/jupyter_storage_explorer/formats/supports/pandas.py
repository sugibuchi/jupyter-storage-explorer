"""Formats handled with pandas: the data browser, on the first rows (pandas
reads eagerly), and load code."""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.packages import Openpyxl, Pandas, PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    FormatSupport,
    SupportOptions,
    format_kwargs,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import QueryView

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits

AS_DATA_FRAME = "Load as DataFrame"


def _rows(limits: ViewLimits) -> int:
    """Rows read for the data browser: pandas reads eagerly, so at most
    ``max_memory_rows``, and one more, which tells whether there are more."""
    return limits.max_memory_rows + 1


def _query_view(df: Any, limits: ViewLimits) -> QueryView:
    """The rows read (see ``_rows``) in the data browser, which says when
    they are only the first of the data."""
    more = len(df) > limits.max_memory_rows
    return QueryView(data=df.head(limits.max_memory_rows), more=more)


class PandasEngine(Engine):
    key = "pandas"
    label = "pandas"
    requirements = (Pandas(),)


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

    engine = PandasEngine
    options_model = PandasOptions


class CsvByPandas(_PandasByUrl):
    format = Csv
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Csv, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        pd = Pandas().load()
        # The separator, from the beginning; the rows, read through the
        # explorer's filesystem, so any storage works.
        text, _ = ctx.head_text(limits.max_bytes)
        with ctx.fs.open(ctx.path, "rb") as f:
            df = pd.read_csv(f, sep=fmt.separator(ctx.name, text), nrows=_rows(limits))
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_csv({url}{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(ctx.library_url),
                kwargs=format_kwargs(
                    sep=fmt.code_separator(ctx),
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
        with ctx.fs.open(ctx.path, "rt", encoding="utf-8") as f:
            df = pd.read_json(f, lines=True, nrows=_rows(limits))
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}, lines=True{kwargs})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(ctx.library_url),
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
                url=repr(ctx.library_url),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }


class ExcelByPandas(_PandasByUrl):
    format = Excel
    additional_requirements = (Openpyxl(),)  # pandas' Excel engine
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Excel, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        # The first sheet, as polars reads it (ExcelByPolars).
        pd = Pandas().load()
        df = pd.read_excel(
            io.BytesIO(ctx.read_whole(limits)), engine="openpyxl", nrows=_rows(limits)
        )
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_excel({url}{kwargs})
        """)

    def recipe(
        self, fmt: Excel, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(ctx.library_url),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }


class ParquetByPandas(_PandasByUrl):
    format = Parquet
    additional_requirements = (PyArrow(),)  # pandas' Parquet engine
    capabilities = ("view", "recipe")

    def view(
        self, fmt: Parquet, ctx: ItemContext, options: PandasOptions, limits: ViewLimits
    ) -> View:
        pa_dataset = PyArrow().load("dataset")
        # pyarrow reads through the explorer's fsspec filesystem, so any
        # storage works. A directory's data files are those polars reads
        # (Parquet.data_url): its partition folders' (their columns from the
        # folders' names), not its other folders' (e.g. Spark's "_temporary").
        options: dict[str, Any] = {}
        if not ctx.is_dir:
            source: Any = ctx.path
        else:
            source = sorted(
                path
                for path in ctx.fs.glob(fmt.data_url(ctx, ctx.path))
                if not path.rstrip("/").rsplit("/", 1)[-1].startswith((".", "_"))
            )
            if fmt.layout(ctx).keys:
                options = {"partitioning": "hive", "partition_base_dir": ctx.path}
        if not source:
            raise ValueError("no Parquet files found")
        dataset = pa_dataset.dataset(
            source, filesystem=ctx.fs, format="parquet", **options
        )
        return _query_view(dataset.head(_rows(limits)).to_pandas(), limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_parquet({url}{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: PandasOptions
    ) -> dict[str, str]:
        return {
            AS_DATA_FRAME: self.data_frame_template.format(
                url=repr(ctx.library_url),
                kwargs=format_kwargs(
                    storage_options=options.code_value("storage_options")
                ),
            )
        }
