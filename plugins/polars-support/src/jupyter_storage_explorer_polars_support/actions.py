"""Formats handled with polars, as actions: the data browser and load code.

Each format has a view and one code action per snippet, registered in order
in ``POLARS_ACTIONS``. polars is imported inside the functions, so that the
plugin loads without it."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.actions import (
    ActionOptions,
    code,
    get_logger,
    register_actions,
    view,
)
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.engine import Engine
from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.packages import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.packages import Fsspec, PyArrow, PythonPackage
from jupyter_storage_explorer.util import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    format_arguments,
    format_kwargs,
    format_size,
    option_field,
    secret_dict_field,
    secret_field,
)
from jupyter_storage_explorer.views import (
    Leaf,
    QueryView,
    TableSetView,
    View,
    ViewLimits,
    ViewWithChoice,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.parquet import ParquetLayout

log = get_logger(__name__)

AS_LAZY_FRAME = "Load as LazyFrame"
AS_DATA_FRAME = "Load as DataFrame"


# The engine's library, and those only polars uses (the support libraries
# several engines use are the core's: jupyter_storage_explorer.packages).


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
class FsspecCodeOptions(ActionOptions):
    """The options of code opening the file with fsspec for polars: Excel's
    always, the other formats' on storages polars cannot read itself.
    """

    fsspec_storage_options: Mapping[str, Any] | None = secret_dict_field(
        description=(
            "`fsspec.open`'s keyword arguments in the code that opens the file "
            "with fsspec: Excel's code, and the other formats' on storages "
            "polars cannot read itself. Those that look like credentials are "
            "left out."
        ),
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
    """The options of the formats polars reads by URL."""

    storage_options: Mapping[str, Any] | None = secret_dict_field(
        description=(
            "polars' `storage_options`: object_store's keys, not fsspec's ([AWS"
            "](https://docs.rs/object_store/latest/object_store/aws/enum.Amazon"
            "S3ConfigKey.html), [GCP](https://docs.rs/object_store/latest/objec"
            "t_store/gcp/enum.GoogleConfigKey.html), [Azure](https://docs.rs/ob"
            "ject_store/latest/object_store/azure/enum.AzureConfigKey.html); "
            "Delta Lake's are [delta-rs'](https://delta-io.github.io/delta-"
            "rs/latest/usage/loading-table/)). Without them, polars reads "
            "credentials from the environment."
        ),
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
    credential_provider: Any = secret_field(
        description=(
            "polars' `credential_provider`: a function giving cloud storage "
            "credentials; see "
            "[Authentication](https://github.com/sugibuchi/jupyter-storage-"
            "explorer/blob/main/plugins/polars-"
            "support/README.md#authentication)."
        ),
        default="auto",
    )

    def storage(self) -> dict[str, Any]:
        """polars' keyword arguments reaching the storage."""
        return {
            "storage_options": self.storage_options,
            "credential_provider": self.credential_provider,
        }


# Each format's options below are its polars reader's arguments, of the same
# names (polars' API documentation: scan_csv, scan_ndjson, scan_parquet,
# scan_delta, read_excel, read_json), but the source, the storage's (above)
# and functions; LIBRARY_DEFAULT leaves one to polars. The plugin's README
# shows their descriptions, by docs/scripts/option_tables.py.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class CsvByPolarsOptions(PolarsOptions):
    """polars' ``scan_csv`` (``read_csv`` in the code) arguments, besides
    the storage's: unset ones are left to polars, but in the data browser
    ``separator`` (detected from the file's beginning), ``try_parse_dates``
    and ``truncate_ragged_lines`` (True). The code passes ``separator``, as
    detected, and those given. The plugin's README lists them."""

    has_header: bool | _Default = option_field(
        (
            "Indicate if the first row of the dataset is a header or not. If "
            "set to False, column names will be autogenerated in the following "
            "format: `column_x`, with `x` being an enumeration over every "
            "column in the dataset, starting at 0."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    separator: str | _Default = option_field(
        "Single byte character to use as separator in the file.",
        default=LIBRARY_DEFAULT,
        shown_default="detected",
    )
    comment_prefix: str | _Default | None = option_field(
        (
            "A string used to indicate the start of a comment line. Comment "
            "lines are skipped during parsing. Common examples of comment "
            "prefixes are `#` and `//`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    quote_char: str | _Default | None = option_field(
        (
            'Single byte character used for csv quoting, default = `"`. Set to '
            "None to turn off special handling and escaping of quotes."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'\"'`",
    )
    skip_rows: int | _Default = option_field(
        (
            "Start reading after `skip_rows` rows. The header will be parsed at"
            " this offset. Note that we respect CSV escaping/comments when "
            "skipping rows. If you want to skip by newline char only, use "
            "`skip_lines`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    skip_lines: int | _Default = option_field(
        (
            "Start reading after `skip_lines` lines. The header will be parsed "
            "at this offset. Note that CSV escaping will not be respected when "
            "skipping lines. If you want to skip valid CSV rows, use "
            "`skip_rows`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    schema: Any = option_field(
        (
            "Provide the schema. This means that polars doesn't do schema "
            "inference. This argument expects the complete schema, whereas "
            "`schema_overrides` can be used to partially overwrite a schema. "
            "Note that the order of the columns in the provided `schema` must "
            "match the order of the columns in the CSV being read."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    schema_overrides: Any = option_field(
        (
            "Overwrite dtypes during inference; should be a {colname:dtype,} "
            "dict or, if providing a list of strings to `new_columns`, a list "
            "of dtypes of the same length."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    null_values: str | Sequence[str] | Mapping[str, str] | _Default | None = (
        option_field(
            (
                "Values to interpret as null values. You can provide a:\n• `str`:"
                " All values equal to this string will be null.\n• `List[str]`: "
                "All values equal to any string in this list will be null.\n• "
                "`Dict[str, str]`: A dictionary that maps column name to a null "
                "value string."
            ),
            default=LIBRARY_DEFAULT,
            shown_default="`None`",
        )
    )
    empty_string_is_null: bool | _Default = option_field(
        (
            "By default a missing string value is considered to be null. If "
            "`empty_string_is_null` is set to False, missing string values are "
            "considered to decoded as empty strings."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    ignore_errors: bool | _Default = option_field(
        (
            "Try to keep reading lines if some lines yield errors. First try "
            "`infer_schema=False` to read all columns as `pl.String` to check "
            "which values might cause an issue."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    infer_schema: bool | _Default = option_field(
        (
            "When `True`, the schema is inferred from the data using the first "
            "`infer_schema_length` rows. When `False`, the schema is not "
            "inferred and will be `pl.String` if not specified in `schema` or "
            "`schema_overrides`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    infer_schema_length: int | _Default | None = option_field(
        (
            "The maximum number of rows to scan for schema inference. This "
            "applies individually to each file included according to "
            "`infer_schema_files`. If set to `None`, the full data will be "
            "scanned into memory **(this is slow)**. Alternatively set "
            "`infer_schema=False` to read all columns as `pl.String`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`100`",
    )
    infer_schema_files: int | _Default = option_field(
        (
            "How many files to use when inferring schema.\n*Unstable* in "
            "polars: it may change at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`10`",
    )
    n_rows: int | _Default | None = option_field(
        "Stop reading from CSV file after reading `n_rows`.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding: str | _Default = option_field(
        (
            "Lossy means that invalid utf8 values are replaced with `�` "
            'characters. Defaults to "utf8".'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'utf8'`",
    )
    low_memory: bool | _Default = option_field(
        "Reduce memory pressure at the expense of performance.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    skip_rows_after_header: int | _Default = option_field(
        "Skip this number of rows when the header is parsed.",
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    row_index_name: str | _Default | None = option_field(
        (
            "If not None, this will insert a row index column with the given "
            "name into the DataFrame."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    row_index_offset: int | _Default = option_field(
        ("Offset to start the row index column (only used if the name is set)."),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    try_parse_dates: bool | _Default = option_field(
        (
            "Try to automatically parse dates. Most ISO8601-like formats can be"
            " inferred, as well as a handful of others. If this does not "
            "succeed, the column remains of data type `pl.String`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`; data browser: `True`",
    )
    eol_char: str | _Default = option_field(
        (
            "Single byte end of line character (default: `\\n`). When "
            "encountering a file with windows line endings (`\\r\\n`), one can go"
            " with the default `\\n`. The extra `\\r` will be removed when "
            "processed."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'\\n'`",
    )
    new_columns: Sequence[str] | _Default | None = option_field(
        (
            "Provide an explicit list of string column names to use (for "
            "example, when scanning a headerless CSV file). If the given list "
            "is shorter than the width of the DataFrame the remaining columns "
            "will have their original name."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    truncate_ragged_lines: bool | _Default | None = option_field(
        "Truncate lines that are longer than the schema.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: `True`",
    )
    raise_if_empty: bool | _Default | None = option_field(
        (
            "Control behavior when scanning empty files:\n• `True`: Raise a "
            "`NoDataError`.\n• `False`: Return 0 rows.\nThis defaults to "
            "`False` if `has_header=False` and a `schema` is specified, and "
            "`True` otherwise."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    decimal_comma: bool | _Default = option_field(
        ("Parse floats using a comma as the decimal separator instead of a period."),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    glob: bool | _Default = option_field(
        "Expand path given via globbing rules.",
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    include_file_paths: str | _Default | None = option_field(
        "Include the path of the source file(s) as a column with this name.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    extra_columns: str | _Default | None = option_field(
        (
            "Configuration for behavior when extra columns outside of the "
            "defined schema are encountered in the data:\n• `ignore`: "
            "Silently ignores.\n• `raise`: Raises an error.\n*Unstable* in "
            "polars: it may change at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    missing_columns: str | _Default | None = option_field(
        (
            "Configuration for behavior when columns defined in the schema are "
            'missing from the data:\n• `"insert"`: Insert the missing columns'
            ' with NULL values.\n• `"raise"`: Raise an error.\n*Unstable* '
            "in polars: it may change at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPolarsOptions(PolarsOptions):
    """polars' ``scan_ndjson`` (``read_ndjson``) arguments, besides the
    storage's: unset ones are left to polars. The plugin's README lists
    them."""

    schema: Any = option_field(
        (
            "The DataFrame schema may be declared in several ways:\n• As a "
            "dict of {name:type} pairs; if type is None, it will be auto-"
            "inferred.\n• As a list of column names; in this case types are "
            "automatically inferred.\n• As a list of (name,type) pairs; this "
            "is equivalent to the dictionary form.\nIf you supply a list of "
            "column names that does not match the names in the underlying data,"
            " the names given here will overwrite them. The number of names "
            "given in the schema should match the underlying data dimensions."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    schema_overrides: Any = option_field(
        (
            "Support type specification or override of one or more columns; "
            "note that any dtypes inferred from the schema param will be "
            "overridden."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    infer_schema_length: int | _Default | None = option_field(
        (
            "The maximum number of rows to scan for schema inference. If set to"
            " `None`, the full data may be scanned *(this is slow)*."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`100`",
    )
    batch_size: int | _Default | None = option_field(
        "Number of rows to read in each batch.",
        default=LIBRARY_DEFAULT,
        shown_default="`1024`",
    )
    n_rows: int | _Default | None = option_field(
        "Stop reading from JSON file after reading `n_rows`.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    low_memory: bool | _Default = option_field(
        "Reduce memory pressure at the expense of performance.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    row_index_name: str | _Default | None = option_field(
        (
            "If not None, this will insert a row index column with give name "
            "into the DataFrame"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    row_index_offset: int | _Default = option_field(
        "Offset to start the row index column (only use if the name is set)",
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    ignore_errors: bool | _Default = option_field(
        "Return `Null` if parsing fails because of schema mismatches.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    include_file_paths: str | _Default | None = option_field(
        "Include the path of the source file(s) as a column with this name.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


@dataclass(frozen=True, kw_only=True)
class JsonByPolarsOptions(FsspecCodeOptions):
    """polars' ``read_json`` arguments, in the code (JSON is viewed as a
    tree): unset ones are left to polars. The plugin's README lists them."""

    schema: Any = option_field(
        (
            "The DataFrame schema may be declared in several ways:\n• As a "
            "dict of {name:type} pairs; if type is None, it will be auto-"
            "inferred.\n• As a list of column names; in this case types are "
            "automatically inferred.\n• As a list of (name,type) pairs; this "
            "is equivalent to the dictionary form.\nIf you supply a list of "
            "column names that does not match the names in the underlying data,"
            " the names given here will overwrite them. The number of names "
            "given in the schema should match the underlying data dimensions."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    schema_overrides: Any = option_field(
        (
            "Support type specification or override of one or more columns; "
            "note that any dtypes inferred from the schema param will be "
            "overridden."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    infer_schema_length: int | _Default | None = option_field(
        (
            "The maximum number of rows to scan for schema inference. If set to"
            " `None`, the full data may be scanned *(this is slow)*."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`100`",
    )


@dataclass(frozen=True, kw_only=True)
class ParquetByPolarsOptions(PolarsOptions):
    """polars' ``scan_parquet`` (``read_parquet``) arguments, besides the
    storage's: unset ones are left to polars, but ``hive_partitioning`` (by
    the folders detected) and ``hidden_file_prefix`` (in the data browser,
    ``[".", "_"]``; in the code, for files named without ".parquet"). The
    code reads a DataFrame by ``scan_parquet(...).collect()`` when
    ``read_parquet`` lacks an argument given. The plugin's README lists
    them."""

    n_rows: int | _Default | None = option_field(
        "Stop reading from parquet file after reading `n_rows`.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    row_index_name: str | _Default | None = option_field(
        (
            "If not None, this will insert a row index column with the given "
            "name into the DataFrame"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    row_index_offset: int | _Default = option_field(
        ("Offset to start the row index column (only used if the name is set)"),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    parallel: str | _Default = option_field(
        (
            "This determines the direction and strategy of parallelism. 'auto' "
            "will try to determine the optimal direction.\nThe `prefiltered` "
            "strategy first evaluates the pushed-down predicates in parallel "
            "and determines a mask of which rows to read. Then, it parallelizes"
            " over both the columns and the row groups while filtering out rows"
            " that do not need to be read. This can provide significant "
            "speedups for large files (i.e. many row-groups) with a predicate "
            "that filters clustered rows or filters heavily. In other cases, "
            "`prefiltered` may slow down the scan compared other "
            "strategies.\nThe `prefiltered` settings falls back to `auto` if "
            "no predicate is given.\nThe `prefiltered` strategy is *unstable*"
            " in polars: it may change at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'auto'`",
    )
    use_statistics: bool | _Default = option_field(
        (
            "Use statistics in the parquet to determine if pages can be skipped"
            " from reading."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    hive_partitioning: bool | _Default | None = option_field(
        (
            "Infer statistics and schema from hive partitioned URL and use them"
            " to prune reads."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="by the folders detected",
    )
    glob: bool | _Default = option_field(
        "Expand path given via globbing rules.",
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    hidden_file_prefix: str | Sequence[str] | _Default | None = option_field(
        (
            "Skip reading files whose names begin with the specified "
            "prefixes.\n*Unstable* in polars: it may change at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: `['.', '_']`",
    )
    schema: Any = option_field(
        (
            "Specify the datatypes of the columns. The datatypes must match the"
            " datatypes in the file(s). If there are extra columns that are not"
            " in the file(s), consider also passing "
            "`missing_columns='insert'`.\n*Unstable* in polars: it may change"
            " at any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    hive_schema: Any = option_field(
        (
            "The column names and data types of the columns by which the data "
            "is partitioned. If set to `None` (default), the schema of the Hive"
            " partitions is inferred.\n*Unstable* in polars: it may change at"
            " any time."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    try_parse_hive_dates: bool | _Default = option_field(
        "Whether to try parsing hive values as date/datetime types.",
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    low_memory: bool | _Default = option_field(
        "Reduce memory pressure at the expense of performance.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    cache: bool | _Default = option_field(
        "Cache the result after reading.",
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    include_file_paths: str | _Default | None = option_field(
        "Include the path of the source file(s) as a column with this name.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    missing_columns: str | _Default = option_field(
        (
            "Configuration for behavior when columns defined in the schema are "
            "missing from the data:\n• `insert`: Inserts the missing columns "
            "using NULLs as the row values.\n• `raise`: Raises an error."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'raise'`",
    )
    extra_columns: str | _Default = option_field(
        (
            "Configuration for behavior when extra columns outside of the "
            "defined schema are encountered in the data:\n• `ignore`: "
            "Silently ignores.\n• `raise`: Raises an error."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'raise'`",
    )


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

    sheet_id: int | Sequence[int] | _Default | None = option_field(
        (
            "Sheet number(s) to convert (set `0` to load all sheets as "
            "DataFrames) and return a `{sheetname:frame,}` dict. (Defaults to "
            "`1` if neither this nor `sheet_name` are specified). Can also take"
            " a sequence of sheet numbers."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    sheet_name: str | Sequence[str] | _Default | None = option_field(
        (
            "Sheet name(s) to convert; cannot be used in conjunction with "
            "`sheet_id`. If more than one is given then a `{sheetname:frame,}` "
            "dict is returned."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    table_name: str | _Default | None = option_field(
        (
            "Name of a specific table to read; note that table names are unique"
            " across the workbook, so additionally specifying a sheet id or "
            "name is optional; if one of those parameters *is* specified, an "
            "error will be raised if the named table is not found in that "
            "particular sheet."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    engine: str | _Default = option_field(
        (
            "Library used to parse the spreadsheet file; defaults to "
            '"calamine".\n• "calamine": this engine can be used for reading '
            "all major types of Excel Workbook (`.xlsx`, `.xlsb`, `.xls`) and "
            "is dramatically faster than the other options, using the "
            "`fastexcel` module to bind the Rust-based Calamine parser.\n• "
            '"openpyxl": this engine is significantly slower than both '
            "`calamine` and `xlsx2csv`, but can provide a useful fallback if "
            "you are otherwise unable to read data from your workbook.\n• "
            '"xlsx2csv": converts the data to an in-memory CSV before using the'
            " native polars `read_csv` method to parse the result."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'calamine'`",
    )
    engine_options: Mapping[str, Any] | _Default | None = option_field(
        (
            "Additional options passed to the underlying engine's primary "
            'parsing constructor (given below), if supported:\n• "calamine": '
            'n/a (can only provide `read_options`)\n• "openpyxl": [load_workb'
            "ook](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader"
            '.excel.html#openpyxl.reader.excel.load_workbook)\n• "xlsx2csv": '
            "[Xlsx2csv](https://github.com/dilshod/xlsx2csv/blob/f35734aa453d65"
            "102198a77e7b8cd04928e6b3a2/xlsx2csv.py#L157)"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    read_options: Mapping[str, Any] | _Default | None = option_field(
        (
            "Options passed to the underlying engine method that reads the "
            "sheet data. Where supported, this allows for additional control "
            "over parsing. The specific read methods associated with each "
            'engine are:\n• "calamine": [load_sheet_by_name](https://fastexce'
            "l.toucantoco.dev/fastexcel.html#ExcelReader.load_sheet_by_name) "
            "(or [load_table](https://fastexcel.toucantoco.dev/fastexcel.html#E"
            "xcelReader.load_table) if using the `table_name` parameter).\n• "
            '"openpyxl": n/a (can only provide `engine_options`)\n• '
            '"xlsx2csv": see `read_csv`'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    has_header: bool | _Default = option_field(
        (
            "Indicate if the first row of the table data is a header or not. If"
            " False, column names will be autogenerated in the following "
            "format: `column_x`, with `x` being an enumeration over every "
            "column in the dataset, starting at 0."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    columns: Sequence[int] | Sequence[str] | str | _Default | None = option_field(
        (
            "Columns to read from the sheet; if not specified, all columns are "
            "read. Can be given as a sequence of column names or indices, or a "
            "single column name."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    schema_overrides: Any = option_field(
        "Support type specification or override of one or more columns.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    infer_schema_length: int | _Default | None = option_field(
        (
            "The maximum number of rows to scan for schema inference. If set to"
            " `None`, the entire dataset is scanned to determine the dtypes, "
            "which can slow parsing for large workbooks. Note that only the "
            '"calamine" and "xlsx2csv" engines support this parameter.'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`100`",
    )
    include_file_paths: str | _Default | None = option_field(
        "Include the path of the source file(s) as a column with this name.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    drop_empty_rows: bool | _Default = option_field(
        ("Indicate whether to omit empty rows when reading data into the DataFrame."),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    drop_empty_cols: bool | _Default = option_field(
        (
            "Indicate whether to omit empty columns (with no headers) when "
            "reading data into the DataFrame (note that empty column "
            "identification may vary depending on the underlying engine being "
            "used)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    raise_if_empty: bool | _Default = option_field(
        (
            "When there is no data in the sheet,`NoDataError` is raised. If "
            "this parameter is set to False, an empty DataFrame (with no "
            "columns) is returned instead."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByPolarsOptions(PolarsOptions):
    """polars' ``scan_delta`` (``read_delta``) arguments, besides the
    storage's: unset ones are left to polars. The plugin's README lists
    them.

    ``storage_options`` are delta-rs' (object_store's), not fsspec's;
    without them, credentials come from the environment.
    """

    version: int | str | _Default | None = option_field(
        (
            "Numerical version or timestamp version of the Delta lake "
            "table.\nNote: If `version` is not provided, the latest version "
            "of delta lake table is read."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    delta_table_options: Mapping[str, Any] | _Default | None = option_field(
        "Additional keyword arguments while reading a Delta lake Table.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    use_pyarrow: bool | _Default = option_field(
        "Flag to enable pyarrow dataset reads.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    pyarrow_options: Mapping[str, Any] | _Default | None = option_field(
        (
            "Keyword arguments while converting a Delta lake Table to pyarrow "
            "table. Use this parameter when filtering on partitioned columns or"
            " to read from a 'fsspec' supported filesystem."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


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


# The checks of the actions below, and what the actions decide with them.
# A LazyFrame's code reads the URL, so it is offered only where polars reads
# the storage itself. Elsewhere, a file's DataFrame code opens it with
# fsspec and gives polars the file, which it reads whole: no LazyFrame,
# which would read it whole all the same. Folders have no code there, but
# Parquet's, which reads a PyArrow dataset as the data browser does.


def _read_by_polars(fmt: DataFormat, ctx: ItemContext, options: ActionOptions) -> bool:
    """Whether polars reads the item by its location itself, lazily: the
    LazyFrame code's and Delta Lake's check."""
    if isinstance(ctx.location, LocalLocation):
        return True
    return ctx.location.url.partition(":")[0].lower() in _READ_BY_POLARS


def _can_offer_recipe(
    fmt: DataFormat, ctx: ItemContext, options: ActionOptions
) -> bool:
    """Whether DataFrame code can load the item: polars reads it itself, or
    the code opens the file with fsspec."""
    return _read_by_polars(fmt, ctx, options) or not ctx.is_dir


def _opened_with_fsspec(
    fmt: DataFormat, ctx: ItemContext, options: ActionOptions
) -> bool:
    """Whether the item's DataFrame code opens it with fsspec: a file polars
    cannot read itself."""
    return not _read_by_polars(fmt, ctx, options) and not ctx.is_dir


# The code reading a URL with polars' {reader}, e.g. "scan_parquet".
_POLARS_TEMPLATE = cleandoc("""
    import polars as pl

    df = pl.{reader}({url}{kwargs})
    """)

# The code reading a file opened with fsspec into a DataFrame, with polars'
# {reader} (e.g. "read_csv") given the file.
_FSSPEC_TEMPLATE = cleandoc("""
    import fsspec
    import polars as pl

    with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
        df = pl.{reader}(f{kwargs})
    """)

# Excel's code: polars reads the bytes, fetched with fsspec so any storage
# works.
_EXCEL_TEMPLATE = cleandoc("""
    import fsspec
    import polars as pl

    with fsspec.open({url}, 'rb'{fsspec_kwargs}) as f:
        df = pl.read_excel(f.read(){kwargs})
    """)


def _fsspec_code(
    reader: str, ctx: ItemContext, options: FsspecCodeOptions, kwargs: str
) -> str:
    """``_FSSPEC_TEMPLATE`` filled for the item."""
    return _FSSPEC_TEMPLATE.format(
        reader=reader,
        url=repr(ctx.url_or_local_path),
        fsspec_kwargs=options.fsspec_kwargs(),
        kwargs=kwargs,
    )


def _polars_code(reader: str, url: str, kwargs: str) -> str:
    """``_POLARS_TEMPLATE`` filled for ``url``."""
    return _POLARS_TEMPLATE.format(reader=reader, url=repr(url), kwargs=kwargs)


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
        started = time.monotonic()
        if first is None:
            data = ctx.fs.cat_file(ctx.path)
        else:
            with ctx.fs.open(ctx.path, "rb") as f:
                data = f.read(first + 1)
        log.info(
            "Read %s %s through fsspec: %d bytes in %.1f s",
            ctx.path,
            "whole" if first is None else "in part",
            len(data),
            time.monotonic() - started,
        )
        cut = first is not None and len(data) > first
        if cut:
            data = data[: data.rfind(b"\n", 0, first) + 1] or data[:first]
        return QueryView(data=scan(io.BytesIO(data)), more=cut)

    if size is not None and size <= limit:
        return read(None)
    log.debug("%s is over %d bytes: the user chooses how much to read", ctx.path, limit)
    whole = f"The whole file ({format_size(size)})" if size else "The whole file"
    first = f"Its first {format_size(limit)}"
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
    options: ActionOptions,
    defaults: Mapping[str, Any] | None = None,
    *,
    storage: bool = True,
) -> str:
    """The code's keyword arguments: the action's ``defaults`` (those not
    None), then the options' arguments given, then the storage options."""
    arguments = {k: v for k, v in (defaults or {}).items() if v is not None}
    arguments.update(options.code_arguments())
    kwargs = format_arguments(arguments)
    if storage:
        kwargs += format_kwargs(storage_options=options.code_value("storage_options"))
    return kwargs


# CSV


@code(format=Csv, engine=PolarsEngine, label=AS_DATA_FRAME, check=_can_offer_recipe)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByPolarsOptions) -> str:
    """A DataFrame, with the separator detected unless one is given."""
    defaults = {"separator": fmt.code_separator(ctx)}
    if _opened_with_fsspec(fmt, ctx, options):
        kwargs = _code_kwargs(options, defaults, storage=False)
        return _fsspec_code("read_csv", ctx, options, kwargs)
    kwargs = _code_kwargs(options, defaults)
    return _polars_code("read_csv", ctx.url_or_local_path, kwargs)


@view(format=Csv, engine=PolarsEngine, code=csv_as_data_frame)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByPolarsOptions, limits: ViewLimits
) -> View:
    """CSV in the data browser, with the separator detected unless one is
    given; through the explorer's filesystem where polars cannot read the
    storage itself."""
    import polars as pl

    url = ctx.url_or_local_path
    native = _read_by_polars(fmt, ctx, options)
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


# JSON Lines


@code(format=JsonLines, engine=PolarsEngine, label=AS_LAZY_FRAME, check=_read_by_polars)
def json_lines_as_lazy_frame(
    ctx: ItemContext, options: JsonLinesByPolarsOptions
) -> str:
    """A LazyFrame of the URL."""
    return _polars_code("scan_ndjson", ctx.url_or_local_path, _code_kwargs(options))


@code(
    format=JsonLines, engine=PolarsEngine, label=AS_DATA_FRAME, check=_can_offer_recipe
)
def json_lines_as_data_frame(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPolarsOptions
) -> str:
    """A DataFrame of the URL, or of the file opened with fsspec."""
    if _opened_with_fsspec(fmt, ctx, options):
        kwargs = _code_kwargs(options, storage=False)
        return _fsspec_code("read_ndjson", ctx, options, kwargs)
    return _polars_code("read_ndjson", ctx.url_or_local_path, _code_kwargs(options))


@view(format=JsonLines, engine=PolarsEngine, code=json_lines_as_lazy_frame)
def json_lines_view(
    fmt: JsonLines,
    ctx: ItemContext,
    options: JsonLinesByPolarsOptions,
    limits: ViewLimits,
) -> View:
    """JSON Lines in the data browser; through the explorer's filesystem
    where polars cannot read the storage itself."""
    import polars as pl

    arguments = options.arguments()
    if not _read_by_polars(fmt, ctx, options):
        return _read_through_fsspec(
            ctx, limits, lambda data: pl.scan_ndjson(data, **arguments)
        )
    data = pl.scan_ndjson(ctx.url_or_local_path, **arguments, **options.storage())
    return QueryView(data=data)


# JSON: code only, as JSON is viewed as a tree (the built-in ``json_view``).


@code(format=Json, engine=PolarsEngine, label=AS_DATA_FRAME, check=_can_offer_recipe)
def json_as_data_frame(
    fmt: Json, ctx: ItemContext, options: JsonByPolarsOptions
) -> str:
    """A DataFrame of the URL, or of the file opened with fsspec."""
    # polars' read_json takes no storage options.
    kwargs = _code_kwargs(options, storage=False)
    if _opened_with_fsspec(fmt, ctx, options):
        return _fsspec_code("read_json", ctx, options, kwargs)
    return _polars_code("read_json", ctx.url_or_local_path, kwargs)


# Excel: fastexcel reads workbooks for polars; the code reads the bytes with
# fsspec, so any storage works.


def _sheets(names: list[str], loader: Callable[[str], Any]) -> TableSetView:
    """A workbook's sheets ``names`` on tabs, as a spreadsheet shows them,
    each read by ``loader(name)``."""
    return TableSetView(
        nodes=[Leaf(label=name, id=name) for name in names],
        loader=loader,
        selector="tab",
    )


@code(
    format=Excel,
    engine=PolarsEngine,
    label=AS_DATA_FRAME,
    requires=(Fastexcel(), Fsspec()),
)
def excel_as_data_frame(ctx: ItemContext, options: ExcelByPolarsOptions) -> str:
    """A DataFrame of the bytes read with fsspec."""
    return _EXCEL_TEMPLATE.format(
        url=repr(ctx.url_or_local_path),
        fsspec_kwargs=options.fsspec_kwargs(),
        kwargs=_code_kwargs(options, storage=False),
    )


@view(
    format=Excel,
    engine=PolarsEngine,
    requires=(Fastexcel(), Fsspec()),
    code=excel_as_data_frame,
)
def excel_view(
    ctx: ItemContext, options: ExcelByPolarsOptions, limits: ViewLimits
) -> View:
    """A workbook's sheets on tabs, each read when chosen, or the sheets the
    options ask for. Excel cannot be read lazily: a sheet is read whole,
    through the explorer's filesystem, and queried in memory."""
    import fastexcel
    import polars as pl

    workbook = ctx.read_whole(limits)
    arguments = options.arguments()
    if {"sheet_id", "sheet_name", "table_name"} & arguments.keys():
        # The sheets (or table) asked for: several make a dict.
        data = pl.read_excel(workbook, **arguments)
        if not isinstance(data, dict):
            return QueryView(data=data)
        return _sheets(list(data), data.__getitem__)
    # The workbook's sheets, each read when chosen: fastexcel (required by
    # this action) only lists them, whichever engine reads them.
    names = fastexcel.read_excel(workbook).sheet_names
    if len(names) == 1:
        return QueryView(data=pl.read_excel(workbook, **arguments))
    return _sheets(
        names, lambda name: pl.read_excel(workbook, sheet_name=name, **arguments)
    )


# Parquet: lazily by URL where polars reads the storage itself; elsewhere
# through a PyArrow dataset over the explorer's filesystem, if PyArrow is
# installed (its engine options then do not apply).


def _pyarrow_dataset(ctx: ItemContext, layout: ParquetLayout | None) -> Any:
    """A LazyFrame over the Parquet file or folder of ``ctx``, on a storage
    polars cannot read itself: a PyArrow dataset read through the explorer's
    filesystem. Lazy, unlike polars' readers given a file object, which read
    the file whole: columns, filters and the first rows are pushed down to
    PyArrow, which reads only the row groups needed, and some ahead. Names
    starting with "." or "_" are skipped, PyArrow's default; partition
    folders give columns, as detected."""
    import polars as pl
    import pyarrow.dataset as ds
    import pyarrow.fs as pa_fs

    dataset = ds.dataset(
        ctx.path,
        filesystem=pa_fs.PyFileSystem(pa_fs.FSSpecHandler(ctx.fs)),
        format="parquet",
        partitioning="hive" if layout is not None and layout.keys else None,
    )
    return pl.scan_pyarrow_dataset(dataset)


def _can_view_parquet(fmt: Parquet, ctx: ItemContext, options: ActionOptions) -> bool:
    """Whether polars reads the item itself, or PyArrow is installed to read
    it through the explorer's filesystem; also the LazyFrame code's check."""
    return _read_by_polars(fmt, ctx, options) or PyArrow().is_installed()


def _can_offer_parquet_recipe(
    fmt: Parquet, ctx: ItemContext, options: ActionOptions
) -> bool:
    """Whether DataFrame code can load the item: as a LazyFrame's can, or a
    file opened with fsspec."""
    return _can_view_parquet(fmt, ctx, options) or not ctx.is_dir


# The code of a PyArrow dataset over the storage's fsspec filesystem, as the
# data browser reads Parquet on storages polars cannot read itself: lazy.
_PYARROW_TEMPLATE = cleandoc("""
    import fsspec
    import polars as pl
    import pyarrow.dataset as ds

    fs, path = fsspec.url_to_fs({url}{fsspec_kwargs})
    dataset = ds.dataset(path, filesystem=fs, format='parquet'{partitioning})
    df = pl.scan_pyarrow_dataset(dataset){collect}
    """)


def _pyarrow_code(
    fmt: Parquet, ctx: ItemContext, options: FsspecCodeOptions, *, collect: bool
) -> str:
    """``_PYARROW_TEMPLATE`` filled for the item: partition folders give
    columns, as in the data browser (``_pyarrow_dataset``)."""
    layout = fmt.layout(ctx) if ctx.is_dir else None
    return _PYARROW_TEMPLATE.format(
        url=repr(ctx.url_or_local_path),
        fsspec_kwargs=options.fsspec_kwargs(),
        partitioning=", partitioning='hive'" if layout and layout.keys else "",
        collect=".collect()" if collect else "",
    )


def _parquet_code_kwargs(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
) -> tuple[str, bool]:
    """The keyword arguments of the code reading the URL, and whether a
    DataFrame must be scanned, then read: ``read_parquet`` lacks an
    argument given (``_SCAN_PARQUET_ONLY``)."""
    layout = fmt.layout(ctx) if ctx.is_dir else None
    # "*" also matches Spark's "_SUCCESS" and checksums.
    hidden = layout is not None and layout.files == "*"
    defaults = {
        "hive_partitioning": True if layout and layout.keys else None,
        "hidden_file_prefix": [".", "_"] if hidden else None,
    }
    scanned = hidden or bool(_SCAN_PARQUET_ONLY & set(options.code_arguments()))
    return _code_kwargs(options, defaults), scanned


@code(format=Parquet, engine=PolarsEngine, label=AS_LAZY_FRAME, check=_can_view_parquet)
def parquet_as_lazy_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
) -> str:
    """A LazyFrame, so only the needed rows and columns are read: of the
    URL, or of a PyArrow dataset where polars cannot read the storage."""
    if not _read_by_polars(fmt, ctx, options):
        return _pyarrow_code(fmt, ctx, options, collect=False)
    kwargs, _ = _parquet_code_kwargs(fmt, ctx, options)
    return _polars_code("scan_parquet", fmt.data_url(ctx), kwargs)


@code(
    format=Parquet,
    engine=PolarsEngine,
    label=AS_DATA_FRAME,
    check=_can_offer_parquet_recipe,
)
def parquet_as_data_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
) -> str:
    """A DataFrame of the URL; where polars cannot read the storage, of a
    PyArrow dataset, or without PyArrow, of the file opened with fsspec."""
    if not _read_by_polars(fmt, ctx, options) and PyArrow().is_installed():
        return _pyarrow_code(fmt, ctx, options, collect=True)
    if _opened_with_fsspec(fmt, ctx, options):
        # A file: none of scan_parquet's own arguments.
        arguments = {
            k: v
            for k, v in options.code_arguments().items()
            if k not in _SCAN_PARQUET_ONLY
        }
        return _fsspec_code("read_parquet", ctx, options, format_arguments(arguments))
    kwargs, scanned = _parquet_code_kwargs(fmt, ctx, options)
    url = fmt.data_url(ctx)
    if scanned:
        # read_parquet lacks an argument given: scanned, then read.
        return f"{_polars_code('scan_parquet', url, kwargs)}.collect()"
    return _polars_code("read_parquet", url, kwargs)


@view(
    format=Parquet,
    engine=PolarsEngine,
    check=_can_view_parquet,
    code=parquet_as_lazy_frame,
)
def parquet_view(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPolarsOptions
) -> View:
    """A LazyFrame over a Parquet file, or over a directory's data files.

    For a directory, its data files as ``matches`` found them (see
    ``Parquet.data_url``); partition folders give columns ("year=2026": a
    column "year"). Names starting with "." or "_" are skipped, as Spark
    writes "_SUCCESS" and ".crc" checksums next to the data.
    """
    import polars as pl

    layout = fmt.layout(ctx) if ctx.is_dir else None
    if not _read_by_polars(fmt, ctx, options):
        log.debug("%s read as a PyArrow dataset through fsspec", ctx.path)
        return QueryView(data=_pyarrow_dataset(ctx, layout))
    log.debug("%s scanned by polars from its URL", ctx.path)
    defaults = {
        "hive_partitioning": layout is not None and bool(layout.keys),
        "hidden_file_prefix": [".", "_"],
    }
    data = pl.scan_parquet(
        fmt.data_url(ctx),
        **{**defaults, **options.arguments()},
        **options.storage(),
    )
    return QueryView(data=data)


# Delta Lake: polars reads the table with deltalake (delta-rs), which reads
# cloud storage itself, by default with credentials from the environment:
# views and code only where it reads the storage.


@code(
    format=DeltaLake,
    engine=PolarsEngine,
    label=AS_LAZY_FRAME,
    requires=(DeltaLakePackage(),),
    check=_read_by_polars,
)
def delta_as_lazy_frame(ctx: ItemContext, options: DeltaLakeByPolarsOptions) -> str:
    """A LazyFrame of the table."""
    return _polars_code("scan_delta", ctx.url_or_local_path, _code_kwargs(options))


@code(
    format=DeltaLake,
    engine=PolarsEngine,
    label=AS_DATA_FRAME,
    requires=(DeltaLakePackage(),),
    check=_read_by_polars,
)
def delta_as_data_frame(ctx: ItemContext, options: DeltaLakeByPolarsOptions) -> str:
    """A DataFrame of the table."""
    return _polars_code("read_delta", ctx.url_or_local_path, _code_kwargs(options))


@view(
    format=DeltaLake,
    engine=PolarsEngine,
    requires=(DeltaLakePackage(),),
    check=_read_by_polars,
    code=delta_as_lazy_frame,
)
def delta_view(
    ctx: ItemContext,
    options: DeltaLakeByPolarsOptions,
) -> View:
    """A LazyFrame over the table."""
    import polars as pl

    url = ctx.url_or_local_path
    data = pl.scan_delta(url, **options.arguments(), **options.storage())
    return QueryView(data=data)


# In the order tried; within a format, its snippets in the order shown.
POLARS_ACTIONS = register_actions(
    delta_view,
    delta_as_lazy_frame,
    delta_as_data_frame,
    parquet_view,
    parquet_as_lazy_frame,
    parquet_as_data_frame,
    csv_view,
    csv_as_data_frame,
    excel_view,
    excel_as_data_frame,
    json_as_data_frame,
    json_lines_view,
    json_lines_as_lazy_frame,
    json_lines_as_data_frame,
)
