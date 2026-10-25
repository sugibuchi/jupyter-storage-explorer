"""Formats handled with pandas, as actions: the data browser, on the first
rows (pandas reads eagerly), and load code.

Each format has a view and its code, registered in order in
``PANDAS_ACTIONS``. pandas is imported inside the functions, so that the
plugin loads without it."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.actions import code, register_actions, view
from jupyter_storage_explorer.formats.base import ItemContext
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.packages import Openpyxl, PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    SupportOptions,
    format_arguments,
    format_kwargs,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import (
    Leaf,
    QueryView,
    TableSetView,
    View,
    ViewLimits,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def _pandas_code(reader: str, url: str, kwargs: str) -> str:
    """The code reading ``url`` with pandas' ``reader``, e.g. "read_csv"."""
    return f"""\
import pandas as pd

df = pd.{reader}({url!r}{kwargs})"""


# CSV


@code(format=Csv, engine=PandasEngine, name=AS_DATA_FRAME)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByPandasOptions) -> str:
    """A DataFrame, with the separator detected unless one is given."""
    kwargs = _code_kwargs(options, {"sep": fmt.code_separator(ctx)})
    return _pandas_code("read_csv", ctx.library_url, kwargs)


@view(format=Csv, engine=PandasEngine, code=csv_as_data_frame)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByPandasOptions, limits: ViewLimits
) -> View:
    """CSV's first rows in the data browser, with the separator detected
    unless one is given."""
    import pandas as pd

    # The separator, from the beginning; the rows, read through the
    # explorer's filesystem, so any storage works.
    arguments = _view_arguments(options, limits)
    if "sep" not in arguments:
        text, _ = ctx.head_text(limits.max_bytes)
        arguments["sep"] = fmt.separator(ctx.name, text)
    with ctx.fs.open(ctx.path, "rb") as f:
        df = pd.read_csv(f, **arguments)
    return _query_view(df, limits)


# JSON Lines


@code(format=JsonLines, engine=PandasEngine, name=AS_DATA_FRAME)
def json_lines_as_data_frame(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPandasOptions
) -> str:
    """A DataFrame of the lines."""
    return f"""\
import pandas as pd

df = pd.read_json({ctx.library_url!r}, lines=True{_code_kwargs(options)})"""


@view(format=JsonLines, engine=PandasEngine, code=json_lines_as_data_frame)
def json_lines_view(
    fmt: JsonLines,
    ctx: ItemContext,
    options: JsonLinesByPandasOptions,
    limits: ViewLimits,
) -> View:
    """JSON Lines' first rows in the data browser."""
    import pandas as pd

    with ctx.fs.open(ctx.path, "rb") as f:
        df = pd.read_json(f, lines=True, **_view_arguments(options, limits))
    return _query_view(df, limits)


# JSON: code only, as JSON is viewed as a tree (the built-in ``json_view``).


@code(format=Json, engine=PandasEngine, name=AS_DATA_FRAME)
def json_as_data_frame(
    fmt: Json, ctx: ItemContext, options: JsonByPandasOptions
) -> str:
    """A DataFrame of the JSON value."""
    return _pandas_code("read_json", ctx.library_url, _code_kwargs(options))


# Excel: openpyxl is pandas' Excel engine.


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


@code(format=Excel, engine=PandasEngine, name=AS_DATA_FRAME, requires=(Openpyxl(),))
def excel_as_data_frame(
    fmt: Excel, ctx: ItemContext, options: ExcelByPandasOptions
) -> str:
    """A DataFrame of the workbook's sheet."""
    return _pandas_code("read_excel", ctx.library_url, _code_kwargs(options))


@view(
    format=Excel,
    engine=PandasEngine,
    requires=(Openpyxl(),),
    code=excel_as_data_frame,
)
def excel_view(
    fmt: Excel, ctx: ItemContext, options: ExcelByPandasOptions, limits: ViewLimits
) -> View:
    """As polars' (``excel_view``): the sheets ``sheet_name`` gives (several
    on tabs), else the workbook's on tabs, or its only sheet."""
    import pandas as pd

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


# Parquet: pyarrow is pandas' Parquet engine.


@code(format=Parquet, engine=PandasEngine, name=AS_DATA_FRAME, requires=(PyArrow(),))
def parquet_as_data_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPandasOptions
) -> str:
    """A DataFrame of the file or folder: pyarrow finds partitions itself."""
    return _pandas_code("read_parquet", ctx.library_url, _code_kwargs(options))


@view(
    format=Parquet,
    engine=PandasEngine,
    requires=(PyArrow(),),
    code=parquet_as_data_frame,
)
def parquet_view(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPandasOptions, limits: ViewLimits
) -> View:
    """A Parquet file's or folder's first rows in the data browser."""
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

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
    dataset = ds.dataset(source, filesystem=ctx.fs, format="parquet", **partitioning)
    # read_parquet's arguments, as pandas applies them with pyarrow.
    arguments = options.arguments()
    filters = arguments.get("filters")
    table = dataset.head(
        _rows(limits),
        columns=arguments.get("columns"),
        filter=None if filters is None else pq.filters_to_expression(filters),
    )
    df = table.to_pandas(**(arguments.get("to_pandas_kwargs") or {}))
    if arguments.get("dtype_backend") is not None:
        df = df.convert_dtypes(dtype_backend=arguments["dtype_backend"])
    return _query_view(df, limits)


# In the order tried; within a format, its view, then its code.
PANDAS_ACTIONS = register_actions(
    parquet_view,
    parquet_as_data_frame,
    csv_view,
    csv_as_data_frame,
    excel_view,
    excel_as_data_frame,
    json_as_data_frame,
    json_lines_view,
    json_lines_as_data_frame,
)
