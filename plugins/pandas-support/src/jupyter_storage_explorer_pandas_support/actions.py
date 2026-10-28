"""Formats handled with pandas, as actions: the data browser, on the first
rows (pandas reads eagerly), and load code.

Each format has a view and its code, registered in order in
``PANDAS_ACTIONS``. pandas is imported inside the functions, so that the
plugin loads without it."""

from __future__ import annotations

import io
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
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.packages import Openpyxl, PyArrow, PythonPackage
from jupyter_storage_explorer.util import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    format_arguments,
    format_kwargs,
    option_field,
    secret_dict_field,
)
from jupyter_storage_explorer.views import (
    Leaf,
    QueryView,
    TableSetView,
    View,
    ViewLimits,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = get_logger(__name__)

AS_DATA_FRAME = "Load as DataFrame"


def _rows(limits: ViewLimits) -> int:
    """Rows read for the data browser: pandas reads eagerly, so at most
    ``max_memory_rows``, and one more, which tells whether there are more."""
    return limits.max_memory_rows + 1


def _query_view(df: Any, limits: ViewLimits) -> QueryView:
    """The rows read (see ``_rows``) in the data browser, which says when
    they are only the first of the data."""
    more = len(df) > limits.max_memory_rows
    log.debug(
        "pandas read %s rows into memory",
        f"the first {limits.max_memory_rows}" if more else f"all {len(df)}",
    )
    return QueryView(data=df.head(limits.max_memory_rows), more=more)


# The engine's library (the support libraries several engines use are the
# core's: jupyter_storage_explorer.packages).


class Pandas(PythonPackage):
    package = "pandas"
    import_name = "pandas"


class PandasEngine(Engine):
    key = "pandas"
    label = "pandas"
    requirements = (Pandas(),)


@dataclass(frozen=True, kw_only=True)
class PandasOptions(ActionOptions):
    """The options of the formats pandas reads."""

    storage_options: Mapping[str, Any] | None = secret_dict_field(
        description=(
            "pandas' `storage_options`, `fsspec.open`'s keyword arguments, in "
            "the code. The data browser reads through the explorer's "
            "filesystem, with its own credentials."
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


# Each format's options below are its pandas reader's arguments, of the same
# names (pandas' API documentation: read_csv, read_json, read_excel,
# read_parquet), but the source, storage_options (above), functions and
# those changing what is returned (iterator, chunksize; lines and orient for
# JSON Lines); LIBRARY_DEFAULT leaves one to pandas. The plugin's README
# shows their descriptions, by docs/scripts/option_tables.py.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class CsvByPandasOptions(PandasOptions):
    """pandas' ``read_csv`` arguments, besides ``storage_options``: unset
    ones are left to pandas, but ``sep`` (detected from the file's
    beginning). The data browser reads at most ``max_memory_rows`` rows
    (fewer with ``nrows``). The plugin's README lists them."""

    sep: str | _Default | None = option_field(
        (
            "Character or regex pattern to treat as the delimiter. `sep=None` "
            "detects the separator from the first valid row of the file with "
            "Python's builtin sniffer tool, `csv.Sniffer`; it is supported only"
            " by the Python parsing engine, which will be used automatically. "
            "In addition, separators longer than 1 character and different from"
            " `'\\s+'` will be interpreted as regular expressions and will also "
            "force the use of the Python parsing engine. Note that regex "
            "delimiters are prone to ignoring quoted data. Regex example: "
            "`'\\r\\t'`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="detected",
    )
    header: int | Sequence[int] | str | _Default | None = option_field(
        (
            "Row number(s) containing column labels and marking the start of "
            "the data (zero-indexed). Default behavior is to infer the column "
            "names: if no `names` are passed the behavior is identical to "
            "`header=0` and column names are inferred from the first line of "
            "the file, if column names are passed explicitly to `names` then "
            "the behavior is identical to `header=None`. Explicitly pass "
            "`header=0` to be able to replace existing names. The header can be"
            " a list of integers that specify row locations for a `MultiIndex` "
            "on the columns e.g. `[0, 1, 3]`. Intervening rows that are not "
            "specified will be skipped (e.g. 2 in this example is skipped). "
            "Note that this parameter ignores commented lines and empty lines "
            "if `skip_blank_lines=True`, so `header=0` denotes the first line "
            "of data rather than the first line of the file.\nWhen inferred "
            "from the file contents, headers are kept distinct from each other "
            "by renaming duplicate names with a numeric suffix of the form "
            '`".{count}"` starting from 1, e.g. `"foo"` and `"foo.1"`. Empty '
            'headers are named `"Unnamed: {i}"` or ` "Unnamed: '
            '{i}_level_{level}"` in the case of MultiIndex columns.'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'infer'`",
    )
    names: Sequence[str] | _Default = option_field(
        (
            "Sequence of column labels to apply. If the file contains a header "
            "row, then you should explicitly pass `header=0` to override the "
            "column names. Duplicates in this list are not allowed."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )
    index_col: int | str | Sequence[int | str] | bool | _Default | None = option_field(
        (
            "Column(s) to use as row label(s), denoted either by column labels "
            "or column indices.  If a sequence of labels or indices is given, "
            "`MultiIndex` will be formed for the row labels.\nNote: "
            "`index_col=False` can be used to force pandas to *not* use the "
            "first column as the index, e.g., when you have a malformed file "
            "with delimiters at the end of each line."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    usecols: Sequence[int | str] | _Default | None = option_field(
        (
            "Subset of columns to select, denoted either by column labels or "
            "column indices. If list-like, all elements must either be "
            "positional (i.e. integer indices into the document columns) or "
            "strings that correspond to column names provided either by the "
            "user in `names` or inferred from the document header row(s). If "
            "`names` are given, the document header row(s) are not taken into "
            "account. For example, a valid list-like `usecols` parameter would "
            "be `[0, 1, 2]` or `['foo', 'bar', 'baz']`. Element order is "
            "ignored, so `usecols=[0, 1]` is the same as `[1, 0]`. To "
            "instantiate a `DataFrame` from `data` with element order preserved"
            " use `pd.read_csv(data, usecols=['foo', 'bar'])[['foo', 'bar']]` "
            "for columns in `['foo', 'bar']` order or `pd.read_csv(data, "
            "usecols=['foo', 'bar'])[['bar', 'foo']]` for `['bar', 'foo']` "
            "order.\nIf callable, the callable function will be evaluated "
            "against the column names, returning names where the callable "
            "function evaluates to `True`. An example of a valid callable "
            "argument would be `lambda x: x.upper() in ['AAA', 'BBB', 'DDD']`. "
            "Using this parameter results in much faster parsing time and lower"
            " memory usage."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dtype: Any = option_field(
        (
            "Data type(s) to apply to either the whole dataset or individual "
            "columns. E.g., `{'a': np.float64, 'b': np.int32, 'c': 'Int64'}` "
            "Use `str` or `object` together with suitable `na_values` settings "
            "to preserve and not interpret `dtype`. If `converters` are "
            "specified, they will be applied INSTEAD of `dtype` conversion. "
            "Specify a `defaultdict` as input where the default determines the "
            "`dtype` of the columns which are not explicitly listed."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    engine: str | _Default | None = option_field(
        (
            "Parser engine to use. The C and pyarrow engines are faster, while "
            "the python engine is currently more feature-complete. "
            "Multithreading is currently only supported by the pyarrow engine. "
            'Some features of the "pyarrow" engine are unsupported or may not '
            "work correctly."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    true_values: Sequence[Any] | _Default | None = option_field(
        (
            "Values to consider as `True` in addition to case-insensitive "
            "variants of 'True'."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    false_values: Sequence[Any] | _Default | None = option_field(
        (
            "Values to consider as `False` in addition to case-insensitive "
            "variants of 'False'."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    skipinitialspace: bool | _Default = option_field(
        "Skip spaces after delimiter.", default=LIBRARY_DEFAULT, shown_default="`False`"
    )
    skiprows: int | Sequence[int] | _Default | None = option_field(
        (
            "Line numbers to skip (0-indexed) or number of lines to skip "
            "(`int`) at the start of the file.\nIf callable, the callable "
            "function will be evaluated against the row indices, returning "
            "`True` if the row should be skipped and `False` otherwise. An "
            "example of a valid callable argument would be `lambda x: x in [0, "
            "2]`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    skipfooter: int | _Default = option_field(
        ("Number of lines at bottom of file to skip (Unsupported with `engine='c'`)."),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    nrows: int | _Default | None = option_field(
        (
            "Number of rows of file to read. Useful for reading pieces of large"
            " files. Refers to the number of data rows in the returned "
            "DataFrame, excluding:\n• The header row containing column "
            "names.\n• Rows before the header row, if `header=1` or "
            "larger.\nExample usage:\n• To read the first 999,999 (non-"
            "header) rows: `read_csv(..., nrows=999999)`\n• To read rows "
            "1,000,000 through 1,999,999: `read_csv(..., skiprows=1000000, "
            "nrows=999999)`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: at most `max_memory_rows`",
    )
    na_values: Any = option_field(
        (
            "Additional strings to recognize as `NA`/`NaN`. If `dict` passed, "
            "specific per-column `NA` values.  By default the following values "
            'are interpreted as `NaN`: empty string, "NaN", "N/A", "NULL", and '
            "other common representations of missing data."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    keep_default_na: bool | _Default = option_field(
        (
            "Whether or not to include the default `NaN` values when parsing "
            "the data. Depending on whether `na_values` is passed in, the "
            "behavior is as follows:\n• If `keep_default_na` is `True`, and "
            "`na_values` are specified, `na_values` is appended to the default "
            "`NaN` values used for parsing.\n• If `keep_default_na` is "
            "`True`, and `na_values` are not specified, only the default `NaN` "
            "values are used for parsing.\n• If `keep_default_na` is `False`,"
            " and `na_values` are specified, only the `NaN` values specified "
            "`na_values` are used for parsing.\n• If `keep_default_na` is "
            "`False`, and `na_values` are not specified, no strings will be "
            "parsed as `NaN`.\nNote that if `na_filter` is passed in as "
            "`False`, the `keep_default_na` and `na_values` parameters will be "
            "ignored."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    na_filter: bool | _Default = option_field(
        (
            "Detect missing value markers (empty strings and the value of "
            "`na_values`). In data without any `NA` values, passing "
            "`na_filter=False` can improve the performance of reading a large "
            "file."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    skip_blank_lines: bool | _Default = option_field(
        ("If `True`, skip over blank lines rather than interpreting as `NaN` values."),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    parse_dates: bool | Sequence[int | str] | _Default | None = option_field(
        (
            "The behavior is as follows:\n• `bool`. If `True` -> try parsing "
            "the index.\n• `None`. Behaves like `True` if `date_format` is "
            "specified.\n• `list` of `int` or names. e.g. If `[1, 2, 3]` -> "
            "try parsing columns 1, 2, 3 each as a separate date column.\nIf "
            "a column or index cannot be represented as an array of `datetime`,"
            " say because of an unparsable value or a mixture of timezones, the"
            " column or index will be returned unaltered as an `object` data "
            "type. For non-standard `datetime` parsing, use `to_datetime` after"
            " `read_csv`.\nNote: A fast-path exists for iso8601-formatted "
            "dates."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    date_format: str | Mapping[str, str] | _Default | None = option_field(
        (
            "Format to use for parsing dates and/or times when used in "
            "conjunction with `parse_dates`. The strftime to parse time, e.g. "
            '`"%d/%m/%Y"`. See [strftime documentation](https://docs.python.org'
            "/3/library/datetime.html#strftime-and-strptime-behavior) for more "
            'information on choices, though note that `"%f"` will parse all the'
            ' way up to nanoseconds. You can also pass:\n• "ISO8601", to '
            "parse any [ISO8601](https://en.wikipedia.org/wiki/ISO_8601) time "
            'string (not necessarily in exactly the same format);\n• "mixed",'
            " to infer the format for each element individually. This is risky,"
            " and you should probably use it along with `dayfirst`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dayfirst: bool | _Default = option_field(
        "DD/MM format dates, international and European format.",
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    cache_dates: bool | _Default = option_field(
        (
            "If `True`, use a cache of unique, converted dates to apply the "
            "`datetime` conversion. May produce significant speed-up when "
            "parsing duplicate date strings, especially ones with timezone "
            "offsets."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    compression: str | Mapping[str, Any] | _Default | None = option_field(
        (
            "For on-the-fly decompression of on-disk data. If 'infer' and "
            "'filepath_or_buffer' is path-like, then detect compression from "
            "the following extensions: '.gz', '.bz2', '.zip', '.xz', '.zst', "
            "'.tar', '.tar.gz', '.tar.xz' or '.tar.bz2' (otherwise no "
            "compression). If using 'zip' or 'tar', the ZIP file must contain "
            "only one data file to be read in. Set to `None` for no "
            "decompression. Can also be a dict with key `'method'` set to one "
            "of {`'zip'`, `'gzip'`, `'bz2'`, `'zstd'`, `'xz'`, `'tar'`} and "
            "other key-value pairs are forwarded to `zipfile.ZipFile`, "
            "`gzip.GzipFile`, `bz2.BZ2File`, `zstandard.ZstdDecompressor`, "
            "`lzma.LZMAFile` or `tarfile.TarFile`, respectively. As an example,"
            " the following could be passed for Zstandard decompression using a"
            " custom compression dictionary: `compression={'method': 'zstd', "
            "'dict_data': my_compression_dict}`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'infer'`",
    )
    thousands: str | _Default | None = option_field(
        "Character acting as the thousands separator in numerical values.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    decimal: str | _Default = option_field(
        ("Character to recognize as decimal point (e.g., use ',' for European data)."),
        default=LIBRARY_DEFAULT,
        shown_default="`'.'`",
    )
    lineterminator: str | _Default | None = option_field(
        "Character used to denote a line break. Only valid with C parser.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    quotechar: str | _Default = option_field(
        (
            "Character used to denote the start and end of a quoted item. "
            "Quoted items can include the `delimiter` and it will be ignored."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'\"'`",
    )
    quoting: int | _Default = option_field(
        (
            "Control field quoting behavior per `csv.QUOTE_*` constants: 0 "
            "(`QUOTE_MINIMAL`, the default: only fields containing special "
            "characters are quoted, e.g. characters defined in `quotechar`, "
            "`delimiter`, or `lineterminator`), 1 (`QUOTE_ALL`), 2 "
            "(`QUOTE_NONNUMERIC`) or 3 (`QUOTE_NONE`)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    doublequote: bool | _Default = option_field(
        (
            "When `quotechar` is specified and `quoting` is not `QUOTE_NONE`, "
            "indicate whether or not to interpret two consecutive `quotechar` "
            "elements INSIDE a field as a single `quotechar` element."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    escapechar: str | _Default | None = option_field(
        "Character used to escape other characters.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    comment: str | _Default | None = option_field(
        (
            "Character indicating that the remainder of line should not be "
            "parsed. If found at the beginning of a line, the line will be "
            "ignored altogether. This parameter must be a single character. "
            "Like empty lines (as long as `skip_blank_lines=True`), fully "
            "commented lines are ignored by the parameter `header` but not by "
            "`skiprows`. For example, if `comment='#'`, parsing "
            "`#empty\\na,b,c\\n1,2,3` with `header=0` will result in `'a,b,c'` "
            "being treated as the header."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding: str | _Default | None = option_field(
        (
            "Encoding to use for UTF when reading/writing (ex. `'utf-8'`). "
            "[List of Python standard "
            "encodings](https://docs.python.org/3/library/codecs.html#standard-"
            "encodings) ."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding_errors: str | _Default | None = option_field(
        (
            "How encoding errors are treated. [List of possible "
            "values](https://docs.python.org/3/library/codecs.html#error-"
            "handlers) ."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'strict'`",
    )
    on_bad_lines: str | _Default = option_field(
        (
            "Specifies what to do upon encountering a bad line (a line with too"
            " many fields). Allowed values are:\n• `'error'`, raise an "
            "Exception when a bad line is encountered.\n• `'warn'`, raise a "
            "warning when a bad line is encountered and skip that line.\n• "
            "`'skip'`, skip bad lines without raising or warning when they are "
            "encountered.\n• Callable, function that will process a single "
            "bad line.\n• With `engine='python'`, function with signature "
            "`(bad_line: list[str]) -> list[str] | None`. `bad_line` is a list"
            " of strings split by the `sep`. If the function returns `None`, "
            "the bad line will be ignored. If the function returns a new `list`"
            " of strings with more elements than expected, a `ParserWarning` "
            "will be emitted while dropping extra elements.\n• With "
            "`engine='pyarrow'`, function with signature as described in "
            "pyarrow documentation: [invalid_row_handler](https://arrow.apache."
            "org/docs/python/generated/pyarrow.csv.ParseOptions.html#pyarrow.cs"
            "v.ParseOptions.invalid_row_handler)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'error'`",
    )
    low_memory: bool | _Default = option_field(
        (
            "Internally process the file in chunks, resulting in lower memory "
            "use while parsing, but possibly mixed type inference.  To ensure "
            "no mixed types either set `False`, or specify the type with the "
            "`dtype` parameter. Note that the entire file is read into a single"
            " `DataFrame` regardless, use the `chunksize` or `iterator` "
            "parameter to return the data in chunks. (Only valid with C "
            "parser)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    memory_map: bool | _Default = option_field(
        (
            "If a filepath is provided for `filepath_or_buffer`, map the file "
            "object directly onto memory and access the data directly from "
            "there. Using this option can improve performance because there is "
            "no longer any I/O overhead."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    float_precision: str | _Default | None = option_field(
        (
            "Specifies which converter the C engine should use for floating-"
            "point values. The options are `None` or `'high'` for the ordinary "
            "converter, `'legacy'` for the original lower precision pandas "
            "converter, and `'round_trip'` for the round-trip converter."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dtype_backend: str | _Default = option_field(
        (
            "Back-end data type applied to the resultant `DataFrame` (still "
            "experimental). If not specified, the default behavior is to not "
            "use nullable data types. If specified, the behavior is as "
            'follows:\n• `"numpy_nullable"`: returns nullable-dtype-backed '
            '`DataFrame`\n• `"pyarrow"`: returns pyarrow-backed nullable '
            "`ArrowDtype` `DataFrame`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPandasOptions(PandasOptions):
    """pandas' ``read_json`` arguments for JSON Lines (``lines=True``),
    besides ``storage_options``: unset ones are left to pandas. The data
    browser reads at most ``max_memory_rows`` rows (fewer with ``nrows``).
    The plugin's README lists them."""

    dtype: Any = option_field(
        (
            "If True, infer dtypes; if a dict of column to dtype, then use "
            "those; if False, then don't infer dtypes at all, applies only to "
            "the data.\nFor all `orient` values except `'table'`, default is "
            "True."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    convert_axes: bool | _Default | None = option_field(
        (
            "Try to convert the axes to the proper dtypes.\nFor all `orient` "
            "values except `'table'`, default is True."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    convert_dates: bool | Sequence[str] | _Default = option_field(
        (
            "If True then default datelike columns may be converted (depending "
            "on keep_default_dates). If False, no dates will be converted. If a"
            " list of column names, then those columns will be converted and "
            "default datelike columns may also be converted (depending on "
            "keep_default_dates)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    keep_default_dates: bool | _Default = option_field(
        (
            "If parsing dates (convert_dates is not False), then try to parse "
            "the default datelike columns. A column label is datelike if\n• "
            "it ends with `'_at'`,\n• it ends with `'_time'`,\n• it begins "
            "with `'timestamp'`,\n• it is `'modified'`, or\n• it is "
            "`'date'`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    precise_float: bool | _Default = option_field(
        (
            "Set to enable usage of higher precision (strtod) function when "
            "decoding string to double values. Default (False) is to use fast "
            "but less precise builtin functionality."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    date_unit: str | _Default | None = option_field(
        (
            "The timestamp unit to detect if converting dates. The default "
            "behaviour is to try and detect the correct precision, but if this "
            "is not desired then pass one of 's', 'ms', 'us' or 'ns' to force "
            "parsing only seconds, milliseconds, microseconds or nanoseconds "
            "respectively."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding: str | _Default | None = option_field(
        "The encoding to use to decode py3 bytes.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding_errors: str | _Default | None = option_field(
        (
            "How encoding errors are treated. [List of possible "
            "values](https://docs.python.org/3/library/codecs.html#error-"
            "handlers) ."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'strict'`",
    )
    compression: str | Mapping[str, Any] | _Default | None = option_field(
        (
            "For on-the-fly decompression of on-disk data. If 'infer' and "
            "'path_or_buf' is path-like, then detect compression from the "
            "following extensions: '.gz', '.bz2', '.zip', '.xz', '.zst', "
            "'.tar', '.tar.gz', '.tar.xz' or '.tar.bz2' (otherwise no "
            "compression). If using 'zip' or 'tar', the ZIP file must contain "
            "only one data file to be read in. Set to `None` for no "
            "decompression. Can also be a dict with key `'method'` set to one "
            "of {`'zip'`, `'gzip'`, `'bz2'`, `'zstd'`, `'xz'`, `'tar'`} and "
            "other key-value pairs are forwarded to `zipfile.ZipFile`, "
            "`gzip.GzipFile`, `bz2.BZ2File`, `zstandard.ZstdDecompressor`, "
            "`lzma.LZMAFile` or `tarfile.TarFile`, respectively. As an example,"
            " the following could be passed for Zstandard decompression using a"
            " custom compression dictionary: `compression={'method': 'zstd', "
            "'dict_data': my_compression_dict}`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'infer'`",
    )
    nrows: int | _Default | None = option_field(
        (
            "The number of lines from the line-delimited jsonfile that has to "
            "be read. This can only be passed if `lines=True`. If this is None,"
            " all the rows will be returned."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: at most `max_memory_rows`",
    )
    dtype_backend: str | _Default = option_field(
        (
            "Back-end data type applied to the resultant `DataFrame` (still "
            "experimental). If not specified, the default behavior is to not "
            "use nullable data types. If specified, the behavior is as "
            'follows:\n• `"numpy_nullable"`: returns nullable-dtype-backed '
            '`DataFrame`\n• `"pyarrow"`: returns pyarrow-backed nullable '
            "`ArrowDtype` `DataFrame`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )
    engine: str | _Default = option_field(
        (
            'Parser engine to use. The `"pyarrow"` engine is only available '
            "when `lines=True`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'ujson'`",
    )


@dataclass(frozen=True, kw_only=True)
class JsonByPandasOptions(PandasOptions):
    """pandas' ``read_json`` arguments, besides ``storage_options``, in the
    code (JSON is viewed as a tree): unset ones are left to pandas. The
    plugin's README lists them."""

    orient: str | _Default | None = option_field(
        (
            "Indication of expected JSON string format. Compatible JSON strings"
            " can be produced by `to_json()` with a corresponding orient value."
            " The set of possible orients is:\n• `'split'` : dict like "
            "`{index -> [index], columns -> [columns], data -> [values]}`\n• "
            "`'records'` : list like `[{column -> value}, ... , {column -> "
            "value}]`\n• `'index'` : dict like `{index -> {column -> "
            "value}}`\n• `'columns'` : dict like `{column -> {index -> "
            "value}}`\n• `'values'` : just the values array\n• `'table'` : "
            "dict like `{'schema': {schema}, 'data': {data}}`\nThe allowed "
            "and default values depend on the value of the `typ` "
            "parameter.\n• when `typ == 'series'`,\n• allowed orients are "
            "`{'split','records','index'}`\n• default is `'index'`\n• The "
            "Series index must be unique for orient `'index'`.\n• when `typ "
            "== 'frame'`,\n• allowed orients are `{'split','records','index',"
            " 'columns','values', 'table'}`\n• default is `'columns'`\n• "
            "The DataFrame index must be unique for orients `'index'` and "
            "`'columns'`.\n• The DataFrame columns must be unique for orients"
            " `'index'`, `'columns'`, and `'records'`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    typ: str | _Default = option_field(
        "The type of object to recover.",
        default=LIBRARY_DEFAULT,
        shown_default="`'frame'`",
    )
    dtype: Any = option_field(
        (
            "If True, infer dtypes; if a dict of column to dtype, then use "
            "those; if False, then don't infer dtypes at all, applies only to "
            "the data.\nFor all `orient` values except `'table'`, default is "
            "True."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    convert_axes: bool | _Default | None = option_field(
        (
            "Try to convert the axes to the proper dtypes.\nFor all `orient` "
            "values except `'table'`, default is True."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    convert_dates: bool | Sequence[str] | _Default = option_field(
        (
            "If True then default datelike columns may be converted (depending "
            "on keep_default_dates). If False, no dates will be converted. If a"
            " list of column names, then those columns will be converted and "
            "default datelike columns may also be converted (depending on "
            "keep_default_dates)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    keep_default_dates: bool | _Default = option_field(
        (
            "If parsing dates (convert_dates is not False), then try to parse "
            "the default datelike columns. A column label is datelike if\n• "
            "it ends with `'_at'`,\n• it ends with `'_time'`,\n• it begins "
            "with `'timestamp'`,\n• it is `'modified'`, or\n• it is "
            "`'date'`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    precise_float: bool | _Default = option_field(
        (
            "Set to enable usage of higher precision (strtod) function when "
            "decoding string to double values. Default (False) is to use fast "
            "but less precise builtin functionality."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    date_unit: str | _Default | None = option_field(
        (
            "The timestamp unit to detect if converting dates. The default "
            "behaviour is to try and detect the correct precision, but if this "
            "is not desired then pass one of 's', 'ms', 'us' or 'ns' to force "
            "parsing only seconds, milliseconds, microseconds or nanoseconds "
            "respectively."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding: str | _Default | None = option_field(
        "The encoding to use to decode py3 bytes.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    encoding_errors: str | _Default | None = option_field(
        (
            "How encoding errors are treated. [List of possible "
            "values](https://docs.python.org/3/library/codecs.html#error-"
            "handlers) ."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'strict'`",
    )
    compression: str | Mapping[str, Any] | _Default | None = option_field(
        (
            "For on-the-fly decompression of on-disk data. If 'infer' and "
            "'path_or_buf' is path-like, then detect compression from the "
            "following extensions: '.gz', '.bz2', '.zip', '.xz', '.zst', "
            "'.tar', '.tar.gz', '.tar.xz' or '.tar.bz2' (otherwise no "
            "compression). If using 'zip' or 'tar', the ZIP file must contain "
            "only one data file to be read in. Set to `None` for no "
            "decompression. Can also be a dict with key `'method'` set to one "
            "of {`'zip'`, `'gzip'`, `'bz2'`, `'zstd'`, `'xz'`, `'tar'`} and "
            "other key-value pairs are forwarded to `zipfile.ZipFile`, "
            "`gzip.GzipFile`, `bz2.BZ2File`, `zstandard.ZstdDecompressor`, "
            "`lzma.LZMAFile` or `tarfile.TarFile`, respectively. As an example,"
            " the following could be passed for Zstandard decompression using a"
            " custom compression dictionary: `compression={'method': 'zstd', "
            "'dict_data': my_compression_dict}`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'infer'`",
    )
    dtype_backend: str | _Default = option_field(
        (
            "Back-end data type applied to the resultant `DataFrame` (still "
            "experimental). If not specified, the default behavior is to not "
            "use nullable data types. If specified, the behavior is as "
            'follows:\n• `"numpy_nullable"`: returns nullable-dtype-backed '
            '`DataFrame`\n• `"pyarrow"`: returns pyarrow-backed nullable '
            "`ArrowDtype` `DataFrame`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )
    engine: str | _Default = option_field(
        (
            'Parser engine to use. The `"pyarrow"` engine is only available '
            "when `lines=True`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'ujson'`",
    )


@dataclass(frozen=True, kw_only=True)
class ExcelByPandasOptions(PandasOptions):
    """pandas' ``read_excel`` arguments, besides ``storage_options``: unset
    ones are left to pandas, but ``engine`` in the data browser
    (``"openpyxl"``). The data browser shows the sheet ``sheet_name`` gives,
    or each of those it gives (a list, or None for all), on tabs; without it,
    the workbook's sheets on tabs, or its only sheet; at most
    ``max_memory_rows`` rows of each (fewer with ``nrows``). The plugin's
    README lists them."""

    sheet_name: str | int | Sequence[str | int] | _Default | None = option_field(
        (
            "Strings are used for sheet names. Integers are used in zero-"
            "indexed sheet positions (chart sheets do not count as a sheet "
            "position). Lists of strings/integers are used to request multiple "
            "sheets. When `None`, will return a dictionary containing "
            "DataFrames for each sheet.\nAvailable cases:\n• Defaults to "
            "`0`: 1st sheet as a `DataFrame`\n• `1`: 2nd sheet as a "
            '`DataFrame`\n• `"Sheet1"`: Load sheet with name "Sheet1"\n• '
            '`[0, 1, "Sheet5"]`: Load first, second and sheet named "Sheet5" as'
            " a dict of `DataFrame`\n• `None`: Returns a dictionary "
            "containing DataFrames for each sheet."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    header: int | Sequence[int] | _Default | None = option_field(
        (
            "Row (0-indexed) to use for the column labels of the parsed "
            "DataFrame. If a list of integers is passed those row positions "
            "will be combined into a `MultiIndex`. Use None if there is no "
            "header."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    names: Sequence[str] | _Default | None = option_field(
        (
            "List of column names to use. If file contains no header row, then "
            "you should explicitly pass header=None."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    index_col: int | str | Sequence[int] | _Default | None = option_field(
        (
            "Column (0-indexed) to use as the row labels of the DataFrame. Pass"
            " None if there is no such column.  If a list is passed, those "
            "columns will be combined into a `MultiIndex`.  If a subset of data"
            " is selected with `usecols`, index_col is based on the "
            "subset.\nMissing values will be forward filled to allow "
            "roundtripping with `to_excel` for `merged_cells=True`. To avoid "
            "forward filling the missing values use `set_index` after reading "
            "the data instead of `index_col`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    usecols: int | str | Sequence[int | str] | _Default | None = option_field(
        (
            "• If None, then parse all columns.\n• If str, then indicates "
            "comma separated list of Excel column letters and column ranges "
            '(e.g. "A:E" or "A,C,E:F"). Ranges are inclusive of both '
            "sides.\n• If list of int, then indicates list of column numbers "
            "to be parsed (0-indexed).\n• If list of string, then indicates "
            "list of column names to be parsed.\n• If callable, then evaluate"
            " each column name against it and parse the column if the callable "
            "returns `True`.\nReturns a subset of the columns according to "
            "behavior above."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dtype: Any = option_field(
        (
            "Data type for data or columns. E.g. {'a': np.float64, 'b': "
            "np.int32} Use `object` to preserve data as stored in Excel and not"
            " interpret dtype, which will necessarily result in `object` dtype."
            " If converters are specified, they will be applied INSTEAD of "
            "dtype conversion. If you use `None`, it will infer the dtype of "
            "each column based on the data."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    engine: str | _Default | None = option_field(
        (
            "If io is not a buffer or path, this must be set to identify io. "
            "Engine compatibility :\n• `openpyxl` supports newer Excel file "
            "formats.\n• `calamine` supports Excel (.xls, .xlsx, .xlsm, "
            ".xlsb) and OpenDocument (.ods) file formats.\n• `odf` supports "
            "OpenDocument file formats (.odf, .ods, .odt).\n• `pyxlsb` "
            "supports Binary Excel files.\n• `xlrd` supports old-style Excel "
            "files (.xls).\nWhen `engine=None`, the following logic will be "
            "used to determine the engine:\n• If `path_or_buffer` is an "
            "OpenDocument format (.odf, .ods, .odt), then "
            "[odf](https://pypi.org/project/odfpy/) will be used.\n• "
            "Otherwise if `path_or_buffer` is an xls format, `xlrd` will be "
            "used.\n• Otherwise if `path_or_buffer` is in xlsb format, "
            "`pyxlsb` will be used.\n• Otherwise `openpyxl` will be used."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: `'openpyxl'`",
    )
    true_values: Sequence[Any] | _Default | None = option_field(
        "Values to consider as True.", default=LIBRARY_DEFAULT, shown_default="`None`"
    )
    false_values: Sequence[Any] | _Default | None = option_field(
        "Values to consider as False.", default=LIBRARY_DEFAULT, shown_default="`None`"
    )
    skiprows: int | Sequence[int] | _Default | None = option_field(
        (
            "Line numbers to skip (0-indexed) or number of lines to skip (int) "
            "at the start of the file. If callable, the callable function will "
            "be evaluated against the row indices, returning True if the row "
            "should be skipped and False otherwise. An example of a valid "
            "callable argument would be `lambda x: x in [0, 2]`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    nrows: int | _Default | None = option_field(
        "Number of rows to parse. Does not include header rows.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: at most `max_memory_rows`",
    )
    na_values: Any = option_field(
        (
            "Additional strings to recognize as NA/NaN. If dict passed, "
            "specific per-column NA values. By default the following values are"
            " interpreted as NaN: '', '#N/A', '#N/A N/A', '#NA', '-1.#IND', "
            "'-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', "
            "'NA', 'NULL', 'NaN', 'None', 'n/a', 'nan', 'null'."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    keep_default_na: bool | _Default = option_field(
        (
            "Whether or not to include the default NaN values when parsing the "
            "data. Depending on whether `na_values` is passed in, the behavior "
            "is as follows:\n• If `keep_default_na` is True, and `na_values` "
            "are specified, `na_values` is appended to the default NaN values "
            "used for parsing.\n• If `keep_default_na` is True, and "
            "`na_values` are not specified, only the default NaN values are "
            "used for parsing.\n• If `keep_default_na` is False, and "
            "`na_values` are specified, only the NaN values specified "
            "`na_values` are used for parsing.\n• If `keep_default_na` is "
            "False, and `na_values` are not specified, no strings will be "
            "parsed as NaN.\nNote that if `na_filter` is passed in as False, "
            "the `keep_default_na` and `na_values` parameters will be ignored."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    na_filter: bool | _Default = option_field(
        (
            "Detect missing value markers (empty strings and the value of "
            "na_values). In data without any NAs, passing `na_filter=False` can"
            " improve the performance of reading a large file."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`True`",
    )
    parse_dates: Any = option_field(
        (
            "The behavior is as follows:\n• `bool`. If True -> try parsing "
            "the index.\n• `list` of int or names. e.g. If [1, 2, 3] -> try "
            "parsing columns 1, 2, 3 each as a separate date column.\n• "
            "`list` of lists. e.g.  If [[1, 3]] -> combine columns 1 and 3 and "
            "parse as a single date column.\n• `dict`, e.g. {'foo' : [1, 3]} "
            "-> parse columns 1, 3 as date and call result 'foo'\nIf a column"
            " or index contains an unparsable date, the entire column or index "
            "will be returned unaltered as an object data type. If you don`t "
            "want to parse some cells as date just change their type in Excel "
            'to "Text". For non-standard datetime parsing, use `pd.to_datetime`'
            " after `pd.read_excel`.\nNote: A fast-path exists for "
            "iso8601-formatted dates."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    date_format: str | Mapping[str, str] | _Default | None = option_field(
        (
            "If used in conjunction with `parse_dates`, will parse dates "
            "according to this format. For anything more complex, please read "
            "in as `object` and then apply `to_datetime` as-needed."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    thousands: str | _Default | None = option_field(
        (
            "Thousands separator for parsing string columns to numeric.  Note "
            "that this parameter is only necessary for columns stored as TEXT "
            "in Excel, any numeric columns will automatically be parsed, "
            "regardless of display format."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    decimal: str | _Default = option_field(
        (
            "Character to recognize as decimal point for parsing string columns"
            " to numeric. Note that this parameter is only necessary for "
            "columns stored as TEXT in Excel, any numeric columns will "
            "automatically be parsed, regardless of display format.(e.g. use "
            "',' for European data)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'.'`",
    )
    comment: str | _Default | None = option_field(
        (
            "Comments out remainder of line. Pass a character or characters to "
            "this argument to indicate comments in the input file. Any data "
            "between the comment string and the end of the current line is "
            "ignored."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    skipfooter: int | _Default = option_field(
        "Rows at the end to skip (0-indexed).",
        default=LIBRARY_DEFAULT,
        shown_default="`0`",
    )
    dtype_backend: str | _Default = option_field(
        (
            "Back-end data type applied to the resultant `DataFrame` (still "
            "experimental). If not specified, the default behavior is to not "
            "use nullable data types. If specified, the behavior is as "
            'follows:\n• `"numpy_nullable"`: returns nullable-dtype-backed '
            '`DataFrame`\n• `"pyarrow"`: returns pyarrow-backed nullable '
            "`ArrowDtype` `DataFrame`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )
    engine_kwargs: Mapping[str, Any] | _Default | None = option_field(
        "Arbitrary keyword arguments passed to excel engine.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


@dataclass(frozen=True, kw_only=True)
class ParquetByPandasOptions(PandasOptions):
    """pandas' ``read_parquet`` arguments, besides ``storage_options``:
    unset ones are left to pandas. The data browser reads with pyarrow
    (``engine`` is the code's) at most ``max_memory_rows`` rows. The plugin's
    README lists them."""

    engine: str | _Default = option_field(
        (
            "Parquet library to use. If 'auto', then the option "
            "`io.parquet.engine` is used. The default `io.parquet.engine` "
            "behavior is to try 'pyarrow', falling back to 'fastparquet' if "
            "'pyarrow' is unavailable.\nWhen using the `'pyarrow'` engine and"
            " no storage options are provided and a filesystem is implemented "
            'by both `pyarrow.fs` and `fsspec` (e.g. "s3://"), then the '
            "`pyarrow.fs` filesystem is attempted first. Use the filesystem "
            "keyword with an instantiated fsspec filesystem if you wish to use "
            "its implementation."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'auto'`; data browser: pyarrow",
    )
    columns: Sequence[str] | _Default | None = option_field(
        "If not None, only these columns will be read from the file.",
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dtype_backend: str | _Default = option_field(
        (
            "Back-end data type applied to the resultant `DataFrame` (still "
            "experimental). If not specified, the default behavior is to not "
            "use nullable data types. If specified, the behavior is as "
            'follows:\n• `"numpy_nullable"`: returns nullable-dtype-backed '
            '`DataFrame`\n• `"pyarrow"`: returns pyarrow-backed nullable '
            "`ArrowDtype` `DataFrame`"
        ),
        default=LIBRARY_DEFAULT,
        shown_default="(none)",
    )
    filters: Sequence[Any] | _Default | None = option_field(
        (
            "To filter out data. Filter syntax: [[(column, op, val), ...],...] "
            "where op is [==, =, >, >=, <, <=, !=, in, not in] The innermost "
            "tuples are transposed into a set of filters applied through an "
            "`AND` operation. The outer list combines these sets of filters "
            "through an `OR` operation. A single list of tuples can also be "
            "used, meaning that no `OR` operation between set of filters is to "
            "be conducted.\nUsing this argument will NOT result in row-wise "
            'filtering of the final partitions unless `engine="pyarrow"` is '
            "also specified.  For other engines, filtering is only performed at"
            " the partition level, that is, to prevent the loading of some row-"
            "groups and/or files."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    to_pandas_kwargs: Mapping[str, Any] | _Default | None = option_field(
        ('Keyword arguments to pass through to `to_pandas` when `engine="pyarrow"`.'),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


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


def _view_arguments(options: ActionOptions, limits: ViewLimits) -> dict[str, Any]:
    """The options' arguments for the data browser's rows: ``nrows`` at most
    ``_rows(limits)``."""
    arguments = options.arguments()
    nrows = arguments.get("nrows")
    arguments["nrows"] = _rows(limits) if nrows is None else min(nrows, _rows(limits))
    return arguments


# The code reading {url} with pandas' {reader}, e.g. "read_csv", given
# {kwargs}.
_PANDAS_TEMPLATE = cleandoc("""
    import pandas as pd

    df = pd.{reader}({url}{kwargs})
    """)


def _pandas_code(reader: str, url: str, kwargs: str) -> str:
    """The code reading ``url`` with pandas' ``reader``, e.g. "read_csv"."""
    return _PANDAS_TEMPLATE.format(reader=reader, url=repr(url), kwargs=kwargs)


# CSV


@code(format=Csv, engine=PandasEngine, label=AS_DATA_FRAME)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByPandasOptions) -> str:
    """A DataFrame, with the separator detected unless one is given."""
    kwargs = _code_kwargs(options, {"sep": fmt.code_separator(ctx)})
    return _pandas_code("read_csv", ctx.url_or_local_path, kwargs)


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


@code(format=JsonLines, engine=PandasEngine, label=AS_DATA_FRAME)
def json_lines_as_data_frame(
    ctx: ItemContext, options: JsonLinesByPandasOptions
) -> str:
    """A DataFrame of the lines."""
    kwargs = f", lines=True{_code_kwargs(options)}"
    return _pandas_code("read_json", ctx.url_or_local_path, kwargs)


@view(format=JsonLines, engine=PandasEngine, code=json_lines_as_data_frame)
def json_lines_view(
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


@code(format=Json, engine=PandasEngine, label=AS_DATA_FRAME)
def json_as_data_frame(ctx: ItemContext, options: JsonByPandasOptions) -> str:
    """A DataFrame of the JSON value."""
    return _pandas_code("read_json", ctx.url_or_local_path, _code_kwargs(options))


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


@code(format=Excel, engine=PandasEngine, label=AS_DATA_FRAME, requires=(Openpyxl(),))
def excel_as_data_frame(ctx: ItemContext, options: ExcelByPandasOptions) -> str:
    """A DataFrame of the workbook's sheet."""
    return _pandas_code("read_excel", ctx.url_or_local_path, _code_kwargs(options))


@view(
    format=Excel,
    engine=PandasEngine,
    requires=(Openpyxl(),),
    code=excel_as_data_frame,
)
def excel_view(
    ctx: ItemContext, options: ExcelByPandasOptions, limits: ViewLimits
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


@code(format=Parquet, engine=PandasEngine, label=AS_DATA_FRAME, requires=(PyArrow(),))
def parquet_as_data_frame(ctx: ItemContext, options: ParquetByPandasOptions) -> str:
    """A DataFrame of the file or folder: pyarrow finds partitions itself."""
    return _pandas_code("read_parquet", ctx.url_or_local_path, _code_kwargs(options))


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
