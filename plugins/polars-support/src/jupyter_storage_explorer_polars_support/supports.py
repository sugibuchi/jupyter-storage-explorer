"""Formats handled with polars: the data browser and load code."""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.packages import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.packages import Fsspec, PyArrow
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
from jupyter_storage_explorer.formats.view import (
    Leaf,
    QueryView,
    TableSetView,
    ViewWithChoice,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
    from jupyter_storage_explorer.formats.parquet import ParquetLayout
    from jupyter_storage_explorer.formats.support import Task
    from jupyter_storage_explorer.formats.view import View, ViewLimits

AS_LAZY_FRAME = "Load as LazyFrame"
AS_DATA_FRAME = "Load as DataFrame"


# The engine's library, and those only polars uses (the support libraries
# several engines use are the core's: jupyter_storage_explorer.formats.packages).


class Polars(PythonPackage):
    package = "polars"
    import_name = "polars"


class Fastexcel(PythonPackage):
    """polars' default Excel engine (calamine)."""

    package = "fastexcel"
    import_name = "fastexcel"


class PolarsEngine(Engine):
    key = "polars"
    label = "Polars"
    requirements = (Polars(),)


@dataclass(frozen=True, kw_only=True)
class FsspecCodeOptions(SupportOptions):
    """The options of code opening the file with fsspec for polars: Excel's
    always, the other formats' on storages polars cannot read itself.

    Attributes
    ----------
    fsspec_storage_options : mapping or None, default None
        ``fsspec.open``'s keyword arguments in the code; those that look like
        credentials are left out.
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

    def fsspec_kwargs(self) -> str:
        """``fsspec.open``'s keyword arguments in the code, after the URL and
        mode."""
        return format_kwargs(**(self.code_value("fsspec_storage_options") or {}))


@dataclass(frozen=True, kw_only=True)
class PolarsOptions(FsspecCodeOptions):
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
class JsonByPolarsOptions(FsspecCodeOptions):
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
class ExcelByPolarsOptions(FsspecCodeOptions):
    """polars' ``read_excel`` arguments, and how the code reads the bytes
    (``fsspec_storage_options``): unset ones are left to polars. The data
    browser shows the sheet (or table) ``sheet_id``, ``sheet_name`` or
    ``table_name`` give, or each of those they give, on tabs; without them,
    the workbook's sheets on tabs, or its only sheet. The plugin's README
    lists them."""

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
    """A format polars reads by URL, with the storage options of its readers.

    Its code reads the URL where polars reads the storage itself
    (``reads_itself``). Elsewhere, a file's code opens it with fsspec and
    gives polars the file, which it reads whole, into a DataFrame
    (``fsspec_template``, with the reader's arguments): no LazyFrame, which
    would read it whole all the same. Folders, and formats without that
    template, have no code there."""

    engine = PolarsEngine
    options_model = PolarsOptions
    # The code reading a file opened with fsspec: {url}, {fsspec_kwargs} and
    # {kwargs}; None for none.
    fsspec_template: ClassVar[str | None] = None

    def supports(self, fmt: DataFormat, ctx: ItemContext, task: Task) -> bool:
        coded = task != "recipe" or reads_itself(ctx) or self._fsspec_code(ctx)
        return super().supports(fmt, ctx, task) and coded

    def _fsspec_code(self, ctx: ItemContext) -> bool:
        """Whether the item's code opens it with fsspec."""
        return (
            not reads_itself(ctx)
            and self.fsspec_template is not None
            and not ctx.is_dir
        )

    def _fsspec_recipe(
        self, ctx: ItemContext, options: FsspecCodeOptions, kwargs: str
    ) -> dict[str, str]:
        """The code reading the file opened with fsspec, into a DataFrame."""
        assert self.fsspec_template is not None
        code = self.fsspec_template.format(
            url=repr(ctx.library_url),
            fsspec_kwargs=options.fsspec_kwargs(),
            kwargs=kwargs,
        )
        return {AS_DATA_FRAME: code}


# The URL schemes polars reads itself, with object_store: local paths, the
# cloud storages, HTTP(S) and Hugging Face. Its readers read any other
# storage's files only whole, given as bytes.
_READ_BY_POLARS = frozenset(
    {
        "file",
        "s3",
        "s3a",
        "gs",
        "gcs",
        "az",
        "azure",
        "abfs",
        "abfss",
        "adl",
        "http",
        "https",
        "hf",
    }
)


def reads_itself(ctx: ItemContext) -> bool:
    """Whether polars reads the item by its location itself, lazily."""
    if isinstance(ctx.location, LocalLocation):
        return True
    return ctx.location.url.partition(":")[0].lower() in _READ_BY_POLARS


def _size_text(size: int) -> str:
    """``size`` bytes, as people read it, e.g. "586 MB"."""
    if size < 1024 * 1024:
        return f"{max(size // 1024, 1)} KB"
    return f"{size / (1024 * 1024):,.0f} MB"


def _read_through_fsspec(
    ctx: ItemContext, limits: ViewLimits, scan: Callable[[io.BytesIO], Any]
) -> View:
    """The view of a text format (CSV, JSON Lines) on a storage polars cannot
    read itself: ``scan`` of its bytes, read through the explorer's
    filesystem, so polars parses it as it would by URL.

    A file larger than ``limits.max_whole_file_bytes`` is read only once the
    user chooses: whole, into memory, or its first bytes up to that size,
    cut after their last line."""
    size = ctx.size
    limit = limits.max_whole_file_bytes

    def read(first: int | None) -> View:
        if first is None:
            data = ctx.fs.cat_file(ctx.path)
        else:
            with ctx.fs.open(ctx.path, "rb") as f:
                data = f.read(first + 1)
        cut = first is not None and len(data) > first
        if cut:
            data = data[: data.rfind(b"\n", 0, first) + 1] or data[:first]
        return QueryView(data=scan(io.BytesIO(data)), more=cut)

    if size is not None and size <= limit:
        return read(None)
    whole = f"The whole file ({_size_text(size)})" if size else "The whole file"
    first = f"Its first {_size_text(limit)}"
    return ViewWithChoice(
        message=(
            "Polars cannot read this storage itself: the file is read into "
            "memory, then queried there."
        ),
        choices={first: limit, whole: None},
        factory=read,
        style="button",
        with_cancel=True,
    )


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

    def view(
        self,
        fmt: Csv,
        ctx: ItemContext,
        options: CsvByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        pl = Polars().load()
        url = ctx.library_url
        native = reads_itself(ctx)
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        defaults: dict[str, Any] = {
            "truncate_ragged_lines": True,
            "try_parse_dates": True,
        }
        if options.separator is LIBRARY_DEFAULT:
            if native:
                # The first lines, read by polars too, so any URL it reads works.
                lines = pl.scan_lines(url, **options.storage()).head(20).collect()
                text = "\n".join(lines["line"])
            else:
                text, _ = ctx.head_text(64 * 1024)
            defaults["separator"] = fmt.separator(url, text)
        arguments = {**defaults, **options.arguments()}
        if not native:
            return _read_through_fsspec(
                ctx, limits, lambda data: pl.scan_csv(data, **arguments)
            )
        return QueryView(data=pl.scan_csv(url, **arguments, **options.storage()))

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_csv({url}{kwargs})
        """)

    fsspec_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
            df = pl.read_csv(f{kwargs})
        """)

    def recipe(
        self, fmt: Csv, ctx: ItemContext, options: CsvByPolarsOptions
    ) -> dict[str, str]:
        defaults = {"separator": fmt.code_separator(ctx)}
        if self._fsspec_code(ctx):
            kwargs = _code_kwargs(options, defaults, storage=False)
            return self._fsspec_recipe(ctx, options, kwargs)
        kwargs = _code_kwargs(options, defaults)
        url = repr(ctx.library_url)
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs)}


class JsonLinesByPolars(_PolarsByUrl):
    format = JsonLines
    options_model = JsonLinesByPolarsOptions

    def view(
        self,
        fmt: JsonLines,
        ctx: ItemContext,
        options: JsonLinesByPolarsOptions,
        limits: ViewLimits,
    ) -> View:
        pl = Polars().load()
        arguments = options.arguments()
        if not reads_itself(ctx):
            return _read_through_fsspec(
                ctx, limits, lambda data: pl.scan_ndjson(data, **arguments)
            )
        data = pl.scan_ndjson(ctx.library_url, **arguments, **options.storage())
        return QueryView(data=data)

    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_ndjson({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_ndjson({url}{kwargs})
        """)

    fsspec_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
            df = pl.read_ndjson(f{kwargs})
        """)

    def recipe(
        self, fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPolarsOptions
    ) -> dict[str, str]:
        if self._fsspec_code(ctx):
            kwargs = _code_kwargs(options, storage=False)
            return self._fsspec_recipe(ctx, options, kwargs)
        url = repr(ctx.library_url)
        kwargs = _code_kwargs(options)
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs),
        }


class JsonByPolars(_PolarsByUrl):
    """Load code only: JSON is viewed as a tree (``JsonByPython``)."""

    format = Json
    options_model = JsonByPolarsOptions

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_json({url}{kwargs})
        """)

    fsspec_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
            df = pl.read_json(f{kwargs})
        """)

    def recipe(
        self, fmt: Json, ctx: ItemContext, options: JsonByPolarsOptions
    ) -> dict[str, str]:
        # polars' read_json takes no storage options.
        kwargs = _code_kwargs(options, storage=False)
        if self._fsspec_code(ctx):
            return self._fsspec_recipe(ctx, options, kwargs)
        url = repr(ctx.library_url)
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
        code = self.data_frame_template.format(
            url=repr(ctx.library_url),
            fsspec_kwargs=options.fsspec_kwargs(),
            kwargs=_code_kwargs(options, storage=False),
        )
        return {AS_DATA_FRAME: code}


def _pyarrow_dataset(ctx: ItemContext, layout: ParquetLayout | None) -> Any:
    """A LazyFrame over the Parquet file or folder of ``ctx``, on a storage
    polars cannot read itself: a PyArrow dataset read through the explorer's
    filesystem. Lazy, unlike polars' readers given a file object, which read
    the file whole: columns, filters and the first rows are pushed down to
    PyArrow, which reads only the row groups needed, and some ahead. Names
    starting with "." or "_" are skipped, PyArrow's default; partition
    folders give columns, as detected."""
    pa_fs = PyArrow().load("fs")
    dataset = (
        PyArrow()
        .load("dataset")
        .dataset(
            ctx.path,
            filesystem=pa_fs.PyFileSystem(pa_fs.FSSpecHandler(ctx.fs)),
            format="parquet",
            partitioning="hive" if layout is not None and layout.keys else None,
        )
    )
    return Polars().load().scan_pyarrow_dataset(dataset)


class ParquetByPolars(_PolarsByUrl):
    """Parquet with polars: lazily by URL where polars reads the storage
    itself; elsewhere through a PyArrow dataset over the explorer's
    filesystem, if PyArrow is installed (its engine options then do not
    apply)."""

    format = Parquet
    options_model = ParquetByPolarsOptions

    def supports(self, fmt: Parquet, ctx: ItemContext, task: Task) -> bool:
        reachable = task != "view" or reads_itself(ctx) or PyArrow().is_installed()
        return super().supports(fmt, ctx, task) and reachable

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
        if not reads_itself(ctx):
            return QueryView(data=_pyarrow_dataset(ctx, layout))
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

    fsspec_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
            df = pl.read_parquet(f{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
    ) -> dict[str, str]:
        if self._fsspec_code(ctx):
            # A file: none of scan_parquet's own arguments.
            arguments = {
                k: v
                for k, v in options.code_arguments().items()
                if k not in _SCAN_PARQUET_ONLY
            }
            return self._fsspec_recipe(ctx, options, format_arguments(arguments))
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
    options_model = DeltaLakeByPolarsOptions

    def supports(self, fmt: DeltaLake, ctx: ItemContext, task: Task) -> bool:
        # delta-rs reads the table's storage itself: views only there too.
        return super().supports(fmt, ctx, task) and reads_itself(ctx)

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
