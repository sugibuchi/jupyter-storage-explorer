"""Formats handled with polars: the data browser and load code."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.packages import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.packages import Fastexcel, Fsspec, Polars
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    LIBRARY_DEFAULT,
    FormatSupport,
    LibraryDefault,
    SupportOptions,
    format_arguments,
    format_kwargs,
    secret_dict_field,
    secret_field,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import Leaf, QueryView, TableSetView

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits

AS_LAZY_FRAME = "Load as LazyFrame"
AS_DATA_FRAME = "Load as DataFrame"


class PolarsEngine(Engine):
    key = "polars"
    label = "Polars"
    requirements = (Polars(),)


@dataclass(frozen=True, kw_only=True)
class PolarsOptions(SupportOptions):
    """The options of the formats polars reads by URL.

    Attributes
    ----------
    storage_options : mapping or None, default None
        polars' ``storage_options``, for the data browser and the code; in
        the code, those that look like credentials are left out.
    credential_provider : default "auto"
        polars' ``credential_provider``, for the data browser only.
    """

    storage_options: Mapping[str, Any] | None = secret_dict_field(
        default=None,
        secret_keys=[
            "aws_secret_access_key",
            "aws_session_token",
            "azure_storage_account_key",
            "azure_storage_sas_key",
            "azure_client_secret",
            "google_service_account_key",
        ],
    )
    credential_provider: Any = secret_field(default="auto")

    def storage(self) -> dict[str, Any]:
        """polars' keyword arguments reaching the storage."""
        return {
            "storage_options": self.storage_options,
            "credential_provider": self.credential_provider,
        }


# Each format's options below are its polars reader's arguments, of the same
# names (polars' API documentation: scan_csv, scan_ndjson, scan_parquet,
# scan_delta, read_excel, read_json), but the source, the storage's (above)
# and functions; LIBRARY_DEFAULT leaves one to polars. The plugin's README has
# their tables: keep them in step.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class CsvByPolarsOptions(PolarsOptions):
    """polars' ``scan_csv`` (``read_csv`` in the code) arguments, besides
    the storage's: unset ones are left to polars, but in the data browser
    ``separator`` (detected from the file's beginning), ``try_parse_dates``
    and ``truncate_ragged_lines`` (True). The code passes ``separator``, as
    detected, and those given. The plugin's README lists them."""

    has_header: bool | _Default = LIBRARY_DEFAULT
    separator: str | _Default = LIBRARY_DEFAULT
    comment_prefix: str | _Default | None = LIBRARY_DEFAULT
    quote_char: str | _Default | None = LIBRARY_DEFAULT
    skip_rows: int | _Default = LIBRARY_DEFAULT
    skip_lines: int | _Default = LIBRARY_DEFAULT
    schema: Any = LIBRARY_DEFAULT
    schema_overrides: Any = LIBRARY_DEFAULT
    null_values: str | Sequence[str] | Mapping[str, str] | _Default | None = (
        LIBRARY_DEFAULT
    )
    empty_string_is_null: bool | _Default = LIBRARY_DEFAULT
    ignore_errors: bool | _Default = LIBRARY_DEFAULT
    infer_schema: bool | _Default = LIBRARY_DEFAULT
    infer_schema_length: int | _Default | None = LIBRARY_DEFAULT
    infer_schema_files: int | _Default = LIBRARY_DEFAULT
    n_rows: int | _Default | None = LIBRARY_DEFAULT
    encoding: str | _Default = LIBRARY_DEFAULT
    low_memory: bool | _Default = LIBRARY_DEFAULT
    skip_rows_after_header: int | _Default = LIBRARY_DEFAULT
    row_index_name: str | _Default | None = LIBRARY_DEFAULT
    row_index_offset: int | _Default = LIBRARY_DEFAULT
    try_parse_dates: bool | _Default = LIBRARY_DEFAULT
    eol_char: str | _Default = LIBRARY_DEFAULT
    new_columns: Sequence[str] | _Default | None = LIBRARY_DEFAULT
    truncate_ragged_lines: bool | _Default | None = LIBRARY_DEFAULT
    raise_if_empty: bool | _Default | None = LIBRARY_DEFAULT
    decimal_comma: bool | _Default = LIBRARY_DEFAULT
    glob: bool | _Default = LIBRARY_DEFAULT
    include_file_paths: str | _Default | None = LIBRARY_DEFAULT
    extra_columns: str | _Default | None = LIBRARY_DEFAULT
    missing_columns: str | _Default | None = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPolarsOptions(PolarsOptions):
    """polars' ``scan_ndjson`` (``read_ndjson``) arguments, besides the
    storage's: unset ones are left to polars. The plugin's README lists
    them."""

    schema: Any = LIBRARY_DEFAULT
    schema_overrides: Any = LIBRARY_DEFAULT
    infer_schema_length: int | _Default | None = LIBRARY_DEFAULT
    batch_size: int | _Default | None = LIBRARY_DEFAULT
    n_rows: int | _Default | None = LIBRARY_DEFAULT
    low_memory: bool | _Default = LIBRARY_DEFAULT
    row_index_name: str | _Default | None = LIBRARY_DEFAULT
    row_index_offset: int | _Default = LIBRARY_DEFAULT
    ignore_errors: bool | _Default = LIBRARY_DEFAULT
    include_file_paths: str | _Default | None = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonByPolarsOptions(SupportOptions):
    """polars' ``read_json`` arguments, in the code (JSON is viewed as a
    tree): unset ones are left to polars. The plugin's README lists them."""

    schema: Any = LIBRARY_DEFAULT
    schema_overrides: Any = LIBRARY_DEFAULT
    infer_schema_length: int | _Default | None = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class ParquetByPolarsOptions(PolarsOptions):
    """polars' ``scan_parquet`` (``read_parquet``) arguments, besides the
    storage's: unset ones are left to polars, but ``hive_partitioning`` (by
    the folders detected) and ``hidden_file_prefix`` (in the data browser,
    ``[".", "_"]``; in the code, for files named without ".parquet"). The
    code reads a DataFrame by ``scan_parquet(...).collect()`` when
    ``read_parquet`` lacks an argument given. The plugin's README lists
    them."""

    n_rows: int | _Default | None = LIBRARY_DEFAULT
    row_index_name: str | _Default | None = LIBRARY_DEFAULT
    row_index_offset: int | _Default = LIBRARY_DEFAULT
    parallel: str | _Default = LIBRARY_DEFAULT
    use_statistics: bool | _Default = LIBRARY_DEFAULT
    hive_partitioning: bool | _Default | None = LIBRARY_DEFAULT
    glob: bool | _Default = LIBRARY_DEFAULT
    hidden_file_prefix: str | Sequence[str] | _Default | None = LIBRARY_DEFAULT
    schema: Any = LIBRARY_DEFAULT
    hive_schema: Any = LIBRARY_DEFAULT
    try_parse_hive_dates: bool | _Default = LIBRARY_DEFAULT
    low_memory: bool | _Default = LIBRARY_DEFAULT
    cache: bool | _Default = LIBRARY_DEFAULT
    include_file_paths: str | _Default | None = LIBRARY_DEFAULT
    missing_columns: str | _Default = LIBRARY_DEFAULT
    extra_columns: str | _Default = LIBRARY_DEFAULT


# scan_parquet's arguments read_parquet lacks.
_SCAN_PARQUET_ONLY = frozenset({"hidden_file_prefix", "cache", "extra_columns"})


@dataclass(frozen=True, kw_only=True)
class ExcelByPolarsOptions(SupportOptions):
    """polars' ``read_excel`` arguments, and how the code reads the bytes:
    unset ones are left to polars. The data browser shows the sheet (or
    table) ``sheet_id``, ``sheet_name`` or ``table_name`` give, or each of
    those they give, on tabs; without them, the workbook's sheets on tabs,
    or its only sheet. The plugin's README lists them.

    Attributes
    ----------
    fsspec_storage_options : mapping or None, default None
        ``fsspec.open``'s keyword arguments in the code, which reads the
        bytes with it; those that look like credentials are left out.
    """

    fsspec_storage_options: Mapping[str, Any] | None = secret_dict_field(
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
    sheet_id: int | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    sheet_name: str | Sequence[str] | _Default | None = LIBRARY_DEFAULT
    table_name: str | _Default | None = LIBRARY_DEFAULT
    engine: str | _Default = LIBRARY_DEFAULT
    engine_options: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    read_options: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    has_header: bool | _Default = LIBRARY_DEFAULT
    columns: Sequence[int] | Sequence[str] | str | _Default | None = LIBRARY_DEFAULT
    schema_overrides: Any = LIBRARY_DEFAULT
    infer_schema_length: int | _Default | None = LIBRARY_DEFAULT
    include_file_paths: str | _Default | None = LIBRARY_DEFAULT
    drop_empty_rows: bool | _Default = LIBRARY_DEFAULT
    drop_empty_cols: bool | _Default = LIBRARY_DEFAULT
    raise_if_empty: bool | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByPolarsOptions(PolarsOptions):
    """polars' ``scan_delta`` (``read_delta``) arguments, besides the
    storage's: unset ones are left to polars. The plugin's README lists
    them.

    ``storage_options`` are delta-rs' (object_store's), not fsspec's;
    without them, credentials come from the environment.
    """

    version: int | str | _Default | None = LIBRARY_DEFAULT
    delta_table_options: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    use_pyarrow: bool | _Default = LIBRARY_DEFAULT
    pyarrow_options: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT


class _PolarsByUrl(FormatSupport):
    """A format polars reads by URL, with the storage options of its readers."""

    engine = PolarsEngine
    options_model = PolarsOptions


def _code_kwargs(
    options: SupportOptions,
    defaults: Mapping[str, Any] | None = None,
    *,
    storage: bool = True,
) -> str:
    """The code's keyword arguments: the support's ``defaults`` (those not
    None), then the options' arguments given, then the storage options."""
    arguments = {k: v for k, v in (defaults or {}).items() if v is not None}
    arguments.update(options.code_arguments())
    kwargs = format_arguments(arguments)
    if storage:
        kwargs += format_kwargs(storage_options=options.code_value("storage_options"))
    return kwargs


class CsvByPolars(_PolarsByUrl):
    format = Csv
    options_model = CsvByPolarsOptions
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Csv,
        ctx: ItemContext,
        options: CsvByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        pl = Polars().load()
        url = ctx.library_url
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        defaults: dict[str, Any] = {
            "truncate_ragged_lines": True,
            "try_parse_dates": True,
        }
        if options.separator is LIBRARY_DEFAULT:
            # The first lines, read by polars too, so any URL it reads works.
            lines = pl.scan_lines(url, **options.storage()).head(20).collect()["line"]
            defaults["separator"] = fmt.separator(url, "\n".join(lines))
        data = pl.scan_csv(
            url, **{**defaults, **options.arguments()}, **options.storage()
        )
        return QueryView(data=data)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_csv({url}{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: CsvByPolarsOptions
    ) -> dict[str, str]:
        kwargs = _code_kwargs(options, {"separator": fmt.code_separator(ctx)})
        url = repr(ctx.library_url)
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs)}


class JsonLinesByPolars(_PolarsByUrl):
    format = JsonLines
    options_model = JsonLinesByPolarsOptions
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: JsonLinesByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        data = (
            Polars()
            .load()
            .scan_ndjson(ctx.library_url, **options.arguments(), **options.storage())
        )
        return QueryView(data=data)

    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_ndjson({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_ndjson({url}{kwargs})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPolarsOptions
    ) -> dict[str, str]:
        url = repr(ctx.library_url)
        kwargs = _code_kwargs(options)
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs),
        }


class JsonByPolars(FormatSupport):
    """Load code only: JSON is viewed as a tree (``JsonByPython``)."""

    format = Json
    engine = PolarsEngine
    options_model = JsonByPolarsOptions
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_json({url}{kwargs})
        """)

    def recipe(
        self, fmt: Json, ctx: ItemContext, options: JsonByPolarsOptions
    ) -> dict[str, str]:
        # polars' read_json takes no storage options.
        url = repr(ctx.library_url)
        kwargs = _code_kwargs(options, storage=False)
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs)}


def _sheets(names: list[str], loader: Callable[[str], Any]) -> TableSetView:
    """A workbook's sheets ``names`` on tabs, as a spreadsheet shows them,
    each read by ``loader(name)``."""
    return TableSetView(
        nodes=[Leaf(label=name, id=name) for name in names],
        loader=loader,
        selector="tab",
    )


class ExcelByPolars(FormatSupport):
    format = Excel
    engine = PolarsEngine
    # fastexcel reads workbooks for polars; the code reads the bytes with fsspec.
    additional_requirements = (
        Fastexcel(),
        Fsspec(),
    )
    capabilities = ("view", "recipe")
    options_model = ExcelByPolarsOptions

    def view(
        self,
        fmt: Excel,
        ctx: ItemContext,
        options: ExcelByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        # Excel cannot be read lazily: a sheet is read whole, through the
        # explorer's filesystem, and queried in memory.
        size = ctx.info.get("size")
        if size is not None and size > limits.max_whole_file_bytes:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to view (over {limit} MB)")
        if options.engine in (LIBRARY_DEFAULT, "calamine"):
            Fastexcel().load()  # polars' default engine
        pl = Polars().load()
        workbook = ctx.fs.cat_file(ctx.path)
        arguments = options.arguments()
        if {"sheet_id", "sheet_name", "table_name"} & arguments.keys():
            # The sheets (or table) asked for: several make a dict.
            data = pl.read_excel(workbook, **arguments)
            if not isinstance(data, dict):
                return QueryView(data=data)
            return _sheets(list(data), data.__getitem__)
        # The workbook's sheets, each read when chosen: fastexcel (installed
        # with this support) only lists them, whichever engine reads them.
        names = Fastexcel().load().read_excel(workbook).sheet_names
        if len(names) == 1:
            return QueryView(data=pl.read_excel(workbook, **arguments))
        return _sheets(
            names, lambda name: pl.read_excel(workbook, sheet_name=name, **arguments)
        )

    # polars reads the bytes, fetched with fsspec so any storage works.
    data_frame_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
            df = pl.read_excel(f.read(){kwargs})
        """)

    def recipe(
        self, fmt: Excel, ctx: ItemContext, options: ExcelByPolarsOptions
    ) -> dict[str, str]:
        fsspec_kwargs = format_kwargs(
            **(options.code_value("fsspec_storage_options") or {})
        )
        code = self.data_frame_template.format(
            url=repr(ctx.library_url),
            fsspec_kwargs=fsspec_kwargs,
            kwargs=_code_kwargs(options, storage=False),
        )
        return {AS_DATA_FRAME: code}


class ParquetByPolars(_PolarsByUrl):
    format = Parquet
    options_model = ParquetByPolarsOptions
    capabilities = ("view", "recipe")

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: ParquetByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        """A LazyFrame over a Parquet file, or over a directory's data files.

        For a directory, its data files as ``matches`` found them (see
        ``Parquet.data_url``); partition folders give columns ("year=2026": a
        column "year"). Names starting with "." or "_" are skipped, as Spark
        writes "_SUCCESS" and ".crc" checksums next to the data.
        """
        layout = fmt.layout(ctx) if ctx.is_dir else None
        defaults = {
            "hive_partitioning": layout is not None and bool(layout.keys),
            "hidden_file_prefix": [".", "_"],
        }
        data = (
            Polars()
            .load()
            .scan_parquet(
                fmt.data_url(ctx),
                **{**defaults, **options.arguments()},
                **options.storage(),
            )
        )
        return QueryView(data=data)

    # A LazyFrame, so only the needed rows and columns are read.
    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_parquet({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_parquet({url}{kwargs})
        """)

    # read_parquet takes no hidden_file_prefix (_SCAN_PARQUET_ONLY): scanned,
    # then read.
    data_frame_scanned_template = cleandoc("""
        import polars as pl

        df = pl.scan_parquet({url}{kwargs}).collect()
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
    ) -> dict[str, str]:
        layout = fmt.layout(ctx) if ctx.is_dir else None
        # "*" also matches Spark's "_SUCCESS" and checksums.
        hidden = layout is not None and layout.files == "*"
        defaults = {
            "hive_partitioning": True if layout and layout.keys else None,
            "hidden_file_prefix": [".", "_"] if hidden else None,
        }
        kwargs = _code_kwargs(options, defaults)
        scanned = hidden or bool(_SCAN_PARQUET_ONLY & set(options.code_arguments()))
        data_frame = (
            self.data_frame_scanned_template if scanned else self.data_frame_template
        )
        url = repr(fmt.data_url(ctx))
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: data_frame.format(url=url, kwargs=kwargs),
        }


class DeltaLakeByPolars(_PolarsByUrl):
    format = DeltaLake
    # polars reads the table with deltalake (delta-rs), which reads cloud
    # storage itself, by default with credentials from the environment.
    additional_requirements = (DeltaLakePackage(),)
    capabilities = ("view", "recipe")
    options_model = DeltaLakeByPolarsOptions

    def view(
        self,
        fmt: DeltaLake,
        ctx: ItemContext,
        options: DeltaLakeByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        data = (
            Polars()
            .load()
            .scan_delta(ctx.library_url, **options.arguments(), **options.storage())
        )
        return QueryView(data=data)

    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_delta({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_delta({url}{kwargs})
        """)

    def recipe(
        self, fmt: DeltaLake, ctx: ItemContext, options: DeltaLakeByPolarsOptions
    ) -> dict[str, str]:
        url = repr(ctx.library_url)
        kwargs = _code_kwargs(options)
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs),
        }
