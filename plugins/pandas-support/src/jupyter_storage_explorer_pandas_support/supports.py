"""Formats handled with pandas: the data browser, on the first rows (pandas
reads eagerly), and load code."""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.packages import Openpyxl, PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    LIBRARY_DEFAULT,
    FormatSupport,
    LibraryDefault,
    SupportOptions,
    format_arguments,
    format_kwargs,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import Leaf, QueryView, TableSetView

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


# The engine's library (the support libraries several engines use are the
# core's: jupyter_storage_explorer.formats.packages).


class Pandas(PythonPackage):
    package = "pandas"
    import_name = "pandas"


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


# Each format's options below are its pandas reader's arguments, of the same
# names (pandas' API documentation: read_csv, read_json, read_excel,
# read_parquet), but the source, storage_options (above), functions and
# those changing what is returned (iterator, chunksize; lines and orient for
# JSON Lines); LIBRARY_DEFAULT leaves one to pandas. The plugin's README has
# their tables: keep them in step.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class CsvByPandasOptions(PandasOptions):
    """pandas' ``read_csv`` arguments, besides ``storage_options``: unset
    ones are left to pandas, but ``sep`` (detected from the file's
    beginning). The data browser reads at most ``max_memory_rows`` rows
    (fewer with ``nrows``). The plugin's README lists them."""

    sep: str | _Default | None = LIBRARY_DEFAULT
    header: int | Sequence[int] | str | _Default | None = LIBRARY_DEFAULT
    names: Sequence[str] | _Default = LIBRARY_DEFAULT
    index_col: int | str | Sequence[int | str] | bool | _Default | None = (
        LIBRARY_DEFAULT
    )
    usecols: Sequence[int | str] | _Default | None = LIBRARY_DEFAULT
    dtype: Any = LIBRARY_DEFAULT
    engine: str | _Default | None = LIBRARY_DEFAULT
    true_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    false_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    skipinitialspace: bool | _Default = LIBRARY_DEFAULT
    skiprows: int | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    skipfooter: int | _Default = LIBRARY_DEFAULT
    nrows: int | _Default | None = LIBRARY_DEFAULT
    na_values: Any = LIBRARY_DEFAULT
    keep_default_na: bool | _Default = LIBRARY_DEFAULT
    na_filter: bool | _Default = LIBRARY_DEFAULT
    skip_blank_lines: bool | _Default = LIBRARY_DEFAULT
    parse_dates: bool | Sequence[int | str] | _Default | None = LIBRARY_DEFAULT
    date_format: str | Mapping[str, str] | _Default | None = LIBRARY_DEFAULT
    dayfirst: bool | _Default = LIBRARY_DEFAULT
    cache_dates: bool | _Default = LIBRARY_DEFAULT
    compression: str | Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    thousands: str | _Default | None = LIBRARY_DEFAULT
    decimal: str | _Default = LIBRARY_DEFAULT
    lineterminator: str | _Default | None = LIBRARY_DEFAULT
    quotechar: str | _Default = LIBRARY_DEFAULT
    quoting: int | _Default = LIBRARY_DEFAULT
    doublequote: bool | _Default = LIBRARY_DEFAULT
    escapechar: str | _Default | None = LIBRARY_DEFAULT
    comment: str | _Default | None = LIBRARY_DEFAULT
    encoding: str | _Default | None = LIBRARY_DEFAULT
    encoding_errors: str | _Default | None = LIBRARY_DEFAULT
    on_bad_lines: str | _Default = LIBRARY_DEFAULT
    low_memory: bool | _Default = LIBRARY_DEFAULT
    memory_map: bool | _Default = LIBRARY_DEFAULT
    float_precision: str | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPandasOptions(PandasOptions):
    """pandas' ``read_json`` arguments for JSON Lines (``lines=True``),
    besides ``storage_options``: unset ones are left to pandas. The data
    browser reads at most ``max_memory_rows`` rows (fewer with ``nrows``).
    The plugin's README lists them."""

    dtype: Any = LIBRARY_DEFAULT
    convert_axes: bool | _Default | None = LIBRARY_DEFAULT
    convert_dates: bool | Sequence[str] | _Default = LIBRARY_DEFAULT
    keep_default_dates: bool | _Default = LIBRARY_DEFAULT
    precise_float: bool | _Default = LIBRARY_DEFAULT
    date_unit: str | _Default | None = LIBRARY_DEFAULT
    encoding: str | _Default | None = LIBRARY_DEFAULT
    encoding_errors: str | _Default | None = LIBRARY_DEFAULT
    compression: str | Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    nrows: int | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT
    engine: str | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonByPandasOptions(PandasOptions):
    """pandas' ``read_json`` arguments, besides ``storage_options``, in the
    code (JSON is viewed as a tree): unset ones are left to pandas. The
    plugin's README lists them."""

    orient: str | _Default | None = LIBRARY_DEFAULT
    typ: str | _Default = LIBRARY_DEFAULT
    dtype: Any = LIBRARY_DEFAULT
    convert_axes: bool | _Default | None = LIBRARY_DEFAULT
    convert_dates: bool | Sequence[str] | _Default = LIBRARY_DEFAULT
    keep_default_dates: bool | _Default = LIBRARY_DEFAULT
    precise_float: bool | _Default = LIBRARY_DEFAULT
    date_unit: str | _Default | None = LIBRARY_DEFAULT
    encoding: str | _Default | None = LIBRARY_DEFAULT
    encoding_errors: str | _Default | None = LIBRARY_DEFAULT
    compression: str | Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT
    engine: str | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class ExcelByPandasOptions(PandasOptions):
    """pandas' ``read_excel`` arguments, besides ``storage_options``: unset
    ones are left to pandas, but ``engine`` in the data browser
    (``"openpyxl"``). The data browser shows the sheet ``sheet_name`` gives,
    or each of those it gives (a list, or None for all), on tabs; without it,
    the workbook's sheets on tabs, or its only sheet; at most
    ``max_memory_rows`` rows of each (fewer with ``nrows``). The plugin's
    README lists them."""

    sheet_name: str | int | Sequence[str | int] | _Default | None = LIBRARY_DEFAULT
    header: int | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    names: Sequence[str] | _Default | None = LIBRARY_DEFAULT
    index_col: int | str | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    usecols: int | str | Sequence[int | str] | _Default | None = LIBRARY_DEFAULT
    dtype: Any = LIBRARY_DEFAULT
    engine: str | _Default | None = LIBRARY_DEFAULT
    true_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    false_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    skiprows: int | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    nrows: int | _Default | None = LIBRARY_DEFAULT
    na_values: Any = LIBRARY_DEFAULT
    keep_default_na: bool | _Default = LIBRARY_DEFAULT
    na_filter: bool | _Default = LIBRARY_DEFAULT
    parse_dates: Any = LIBRARY_DEFAULT
    date_format: str | Mapping[str, str] | _Default | None = LIBRARY_DEFAULT
    thousands: str | _Default | None = LIBRARY_DEFAULT
    decimal: str | _Default = LIBRARY_DEFAULT
    comment: str | _Default | None = LIBRARY_DEFAULT
    skipfooter: int | _Default = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT
    engine_kwargs: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class ParquetByPandasOptions(PandasOptions):
    """pandas' ``read_parquet`` arguments, besides ``storage_options``:
    unset ones are left to pandas. The data browser reads with pyarrow
    (``engine`` is the code's) at most ``max_memory_rows`` rows. The plugin's
    README lists them."""

    engine: str | _Default = LIBRARY_DEFAULT
    columns: Sequence[str] | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT
    filters: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    to_pandas_kwargs: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT


def _code_kwargs(
    options: PandasOptions, defaults: Mapping[str, Any] | None = None
) -> str:
    """The code's keyword arguments: the support's ``defaults`` (those not
    None), then the options' arguments given, then ``storage_options``."""
    arguments = {k: v for k, v in (defaults or {}).items() if v is not None}
    arguments.update(options.code_arguments())
    return format_arguments(arguments) + format_kwargs(
        storage_options=options.code_value("storage_options")
    )


def _view_arguments(options: SupportOptions, limits: ViewLimits) -> dict[str, Any]:
    """The options' arguments for the data browser's rows: ``nrows`` at most
    ``_rows(limits)``."""
    arguments = options.arguments()
    nrows = arguments.get("nrows")
    arguments["nrows"] = _rows(limits) if nrows is None else min(nrows, _rows(limits))
    return arguments


class _PandasByUrl(FormatSupport):
    """A format whose code pandas reads by URL, with storage options."""

    engine = PandasEngine
    options_model = PandasOptions


class CsvByPandas(_PandasByUrl):
    format = Csv
    options_model = CsvByPandasOptions
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Csv,
        ctx: ItemContext,
        options: CsvByPandasOptions,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        # The separator, from the beginning; the rows, read through the
        # explorer's filesystem, so any storage works.
        arguments = _view_arguments(options, limits)
        if "sep" not in arguments:
            text, _ = ctx.head_text(limits.max_bytes)
            arguments["sep"] = fmt.separator(ctx.name, text)
        with ctx.fs.open(ctx.path, "rb") as f:
            df = pd.read_csv(f, **arguments)
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_csv({url}{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: CsvByPandasOptions
    ) -> dict[str, str]:
        kwargs = _code_kwargs(options, {"sep": fmt.code_separator(ctx)})
        code = self.data_frame_template.format(url=repr(ctx.library_url), kwargs=kwargs)
        return {AS_DATA_FRAME: code}


class JsonLinesByPandas(_PandasByUrl):
    format = JsonLines
    options_model = JsonLinesByPandasOptions
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: JsonLinesByPandasOptions,
        limits: ViewLimits,
    ) -> View:
        pd = Pandas().load()
        with ctx.fs.open(ctx.path, "rb") as f:
            df = pd.read_json(f, lines=True, **_view_arguments(options, limits))
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}, lines=True{kwargs})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPandasOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            url=repr(ctx.library_url), kwargs=_code_kwargs(options)
        )
        return {AS_DATA_FRAME: code}


class JsonByPandas(_PandasByUrl):
    """Load code only: JSON is viewed as a tree (``JsonByPython``)."""

    format = Json
    options_model = JsonByPandasOptions
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}{kwargs})
        """)

    def recipe(
        self, fmt: Json, ctx: ItemContext, options: JsonByPandasOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            url=repr(ctx.library_url), kwargs=_code_kwargs(options)
        )
        return {AS_DATA_FRAME: code}


def _sheets(
    names: list[str], sheets: Mapping[str, Any], limits: ViewLimits
) -> TableSetView:
    """Sheets read already (``names`` -> ``sheets``) on tabs, as a
    spreadsheet shows them."""
    return TableSetView(
        nodes=[Leaf(label=name, id=name) for name in names],
        loader=lambda name: _query_view(sheets[name], limits),
        selector="tab",
    )


class ExcelByPandas(_PandasByUrl):
    format = Excel
    options_model = ExcelByPandasOptions
    additional_requirements = (Openpyxl(),)  # pandas' Excel engine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Excel,
        ctx: ItemContext,
        options: ExcelByPandasOptions,
        limits: ViewLimits,
    ) -> View:
        # As polars' (ExcelByPolars): the sheets sheet_name gives (several on
        # tabs), else the workbook's on tabs, or its only sheet.
        pd = Pandas().load()
        arguments = {"engine": "openpyxl", **_view_arguments(options, limits)}
        workbook = io.BytesIO(ctx.read_whole(limits))
        if "sheet_name" in arguments:
            data = pd.read_excel(workbook, **arguments)
            if not isinstance(data, dict):
                return _query_view(data, limits)
            return _sheets(
                [str(name) for name in data],
                {str(name): df for name, df in data.items()},
                limits,
            )
        # The workbook, parsed once; each sheet read when chosen.
        # ExcelFile takes the engine's arguments; parse() the others.
        workbook_arguments = {
            key: arguments.pop(key)
            for key in ("engine", "engine_kwargs")
            if key in arguments
        }
        excel = pd.ExcelFile(workbook, **workbook_arguments)
        names = [str(name) for name in excel.sheet_names]
        if len(names) == 1:
            return _query_view(excel.parse(names[0], **arguments), limits)
        return TableSetView(
            nodes=[Leaf(label=name, id=name) for name in names],
            loader=lambda name: _query_view(excel.parse(name, **arguments), limits),
            selector="tab",
        )

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_excel({url}{kwargs})
        """)

    def recipe(
        self, fmt: Excel, ctx: ItemContext, options: ExcelByPandasOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            url=repr(ctx.library_url), kwargs=_code_kwargs(options)
        )
        return {AS_DATA_FRAME: code}


class ParquetByPandas(_PandasByUrl):
    format = Parquet
    options_model = ParquetByPandasOptions
    additional_requirements = (PyArrow(),)  # pandas' Parquet engine
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: ParquetByPandasOptions,
        limits: ViewLimits,
    ) -> View:
        pa_dataset = PyArrow().load("dataset")
        # pyarrow reads through the explorer's fsspec filesystem, so any
        # storage works. A directory's data files are those polars reads
        # (Parquet.data_url): its partition folders' (their columns from the
        # folders' names), not its other folders' (e.g. Spark's "_temporary").
        partitioning: dict[str, Any] = {}
        if not ctx.is_dir:
            source: Any = ctx.path
        else:
            source = sorted(
                path
                for path in ctx.fs.glob(fmt.data_url(ctx, ctx.path))
                if not path.rstrip("/").rsplit("/", 1)[-1].startswith((".", "_"))
            )
            if fmt.layout(ctx).keys:
                partitioning = {"partitioning": "hive", "partition_base_dir": ctx.path}
        if not source:
            raise ValueError("no Parquet files found")
        dataset = pa_dataset.dataset(
            source, filesystem=ctx.fs, format="parquet", **partitioning
        )
        # read_parquet's arguments, as pandas applies them with pyarrow.
        arguments = options.arguments()
        filters = arguments.get("filters")
        table = dataset.head(
            _rows(limits),
            columns=arguments.get("columns"),
            filter=None
            if filters is None
            else PyArrow().load("parquet").filters_to_expression(filters),
        )
        df = table.to_pandas(**(arguments.get("to_pandas_kwargs") or {}))
        if arguments.get("dtype_backend") is not None:
            df = df.convert_dtypes(dtype_backend=arguments["dtype_backend"])
        return _query_view(df, limits)

    data_frame_template = cleandoc("""
        import pandas as pd

        df = pd.read_parquet({url}{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: ParquetByPandasOptions
    ) -> dict[str, str]:
        code = self.data_frame_template.format(
            url=repr(ctx.library_url), kwargs=_code_kwargs(options)
        )
        return {AS_DATA_FRAME: code}
