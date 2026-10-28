"""Formats handled with Dask (``dask.dataframe``), as actions: the data
browser and load code.

Each format has a view and its code, registered in order in
``DASK_ACTIONS``. Dask is imported inside the functions, so that the plugin
loads without it.

How Dask reaches an item, as measured with Dask 2026.8 through a filesystem
counting the bytes read (the plugin's README says it for users):

- Dask reads every storage through fsspec, so the views read through the
  explorer's own filesystem, with its credentials, on every storage.
- Parquet: ``read_parquet`` takes the filesystem itself (``filesystem=``),
  with the item's path in it. A ``DirFileSystem`` is unwrapped first: Dask
  makes its folders' paths absolute, which a ``DirFileSystem`` does not find.
  Making the DataFrame reads the footers only. A file is one partition by
  default, read whole for each page, so a file's partitions are its row
  groups (``split_row_groups=True``): a page reads the first row groups
  only. A folder is read as the glob of its data files, whose partitions
  are its files: given the folder, Dask would read it recursively, Spark's
  ``_temporary`` too.
- CSV and JSON Lines: their readers take only a URL and fsspec's
  ``storage_options``. Given the explorer's, fsspec makes a filesystem like
  the explorer's where it can (``_rebuilt_url``): one of the same class, in
  the reader's threads; elsewhere the file is copied to the kernel's disk
  first, asking for a large one. Making
  the DataFrame reads a sample of the file (256 kB for CSV, 1 MB for JSON
  Lines). Their partitions are blocks of the file, so a page reads the
  first blocks only. Dask makes blocks of one to two times the block size
  asked for, so the data browser asks for half of ``max_whole_file_bytes``:
  a block is never larger. JSON Lines without a block size would be read
  whole when the DataFrame is made, and for each page.
- A filter matching few rows reads every partition, as with any lazy
  library. The core reads Dask's pages partition by partition, and sorted
  ones in one pass (``fetch_rows``).
- The data, made in the view's worker thread, is read in other threads, on
  the scheduler active: Dask's threads, or a distributed ``Client``.
"""

from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

import fsspec
from fsspec.core import split_protocol
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer.actions import (
    ActionOptions,
    code,
    get_logger,
    local_file_cache,
    register_actions,
    view,
)
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.engine import Engine
from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.packages import PyArrow, PythonPackage
from jupyter_storage_explorer.util import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    format_arguments,
    format_kwargs,
    format_size,
    option_field,
    secret_dict_field,
)
from jupyter_storage_explorer.views import (
    QueryView,
    View,
    ViewLimits,
    ViewWithConfirmation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from fsspec.spec import AbstractFileSystem

log = get_logger(__name__)

AS_DATA_FRAME = "Load as DataFrame"

# How long a local copy no view uses is kept, in seconds, so that viewing the
# file again soon reuses it.
_COPY_KEPT = 600


# The engine's libraries: Dask, and pandas, which Dask's partitions are and
# the data browser collects them into. PyArrow, which dask.dataframe
# requires, is the core's (jupyter_storage_explorer.packages).


class Dask(PythonPackage):
    """Dask, with its DataFrame (``dask[dataframe]``)."""

    package = "dask"
    import_name = "dask"


class Pandas(PythonPackage):
    package = "pandas"
    import_name = "pandas"


class DaskEngine(Engine):
    key = "dask"
    label = "Dask"
    requirements = (Dask(), Pandas(), PyArrow())


@dataclass(frozen=True, kw_only=True)
class DaskOptions(ActionOptions):
    """The options of every Dask action."""

    storage_options: Mapping[str, Any] | None = secret_dict_field(
        description=(
            "Dask's `storage_options`, fsspec's keyword arguments, in the code."
            " The data browser reads through the explorer's filesystem, with "
            "its own credentials."
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


# Each format's options below are its Dask reader's arguments, of the same
# names (Dask's API documentation: read_parquet, read_csv, read_json), and
# those of pandas' readers Dask passes on and accepts, checked with Dask
# 2026.8 and pandas 3.1. Left out: the source, storage_options (above),
# filesystem (the explorer's), functions, and arguments Dask refuses or that
# change what is returned (index_col, nrows, iterator, chunksize,
# memory_map; JSON's lines, orient, engine and nrows, which apply to each
# block). LIBRARY_DEFAULT leaves one to Dask. The plugin's README shows their
# descriptions, by docs/scripts/option_tables.py.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class ParquetByDaskOptions(DaskOptions):
    """Dask's ``read_parquet`` arguments, besides ``storage_options``: unset
    ones are left to Dask, but in the data browser ``split_row_groups``
    (True for a file, unless ``blocksize`` is given). The plugin's README
    lists them."""

    columns: Sequence[str] | _Default | None = option_field(
        (
            "Field name(s) to read in as columns in the output. By default all "
            "non-index fields will be read (as determined by the pandas parquet"
            " metadata, if present)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    filters: Sequence[Any] | _Default | None = option_field(
        (
            "List of filters to apply, like `[[('col1', '==', 0), ...], ...]`. "
            "Using this argument will result in row-wise filtering of the final"
            " partitions. Predicates can be expressed in disjunctive normal "
            "form (DNF)."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    index: str | Sequence[str] | bool | _Default | None = option_field(
        (
            "Field name(s) to use as the output frame index. By default will be"
            " inferred from the pandas parquet file metadata, if present. Use "
            "`False` to read all fields as columns."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    categories: Sequence[str] | Mapping[str, int] | _Default | None = option_field(
        (
            "For any fields listed here, if the parquet encoding is Dictionary,"
            " the column will be created with dtype category. Use only if it is"
            " guaranteed that the column is encoded as dictionary in all row-"
            "groups."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    open_file_options: Mapping[str, Any] | _Default | None = option_field(
        (
            "Key/value arguments to be passed along to "
            "`AbstractFileSystem.open` when each parquet data file is open for "
            'reading. Experimental (optimized) "precaching" for remote file '
            'systems can be enabled by adding `{"method": "parquet"}` under the'
            ' `"precache_options"` key.'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    dtype_backend: str | _Default | None = option_field(
        (
            "Which dtype_backend to use, e.g. whether a DataFrame should have "
            "NumPy arrays, nullable dtypes are used for all dtypes that have a "
            "nullable implementation when `'numpy_nullable'` is set, pyarrow is"
            " used for all dtypes if `'pyarrow'` is set."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="NumPy-backed",
    )
    calculate_divisions: bool | _Default = option_field(
        (
            "Whether to use min/max statistics from the footer metadata (or "
            "global `_metadata` file) to calculate divisions for the output "
            "DataFrame collection. May be extremely slow when no global "
            "`_metadata` file is present, especially when reading from remote "
            "storage."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    ignore_metadata_file: bool | _Default = option_field(
        ("Whether to ignore the global `_metadata` file (when one is present)."),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    metadata_task_size: int | _Default | None = option_field(
        (
            "If parquet metadata is processed in parallel, the number of "
            "dataset files to be processed by each task in the Dask graph. `0` "
            "disables parallel metadata processing."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="configurable",
    )
    split_row_groups: str | bool | int | _Default = option_field(
        (
            "If True, then each output dataframe partition will correspond to a"
            " single parquet-file row-group. If False, each partition will "
            "correspond to a complete file. If a positive integer value is "
            "given, each dataframe partition will correspond to that number of "
            "parquet row-groups (or fewer). If `'adaptive'`, the metadata of "
            "each file will be used to ensure that every partition satisfies "
            "`blocksize`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default=(
            "`'infer'`; data browser: `True` for a file, unless `blocksize` is set"
        ),
    )
    blocksize: str | int | _Default | None = option_field(
        (
            "The desired size of each output `DataFrame` partition in terms of "
            "total (uncompressed) parquet storage space. Ignored if "
            "`split_row_groups` is not set to `'infer'` or `'adaptive'`."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`'default'` (256 MiB)",
    )
    aggregate_files: bool | str | _Default | None = option_field(
        (
            "Whether distinct file paths may be aggregated into the same output"
            " partition. Only used when `split_row_groups` is set to `'infer'`,"
            " `'adaptive'` or to an integer >1. For \"hive-partitioned\" "
            'datasets, a "partition"-column name can also be specified.'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    parquet_file_extension: str | Sequence[str] | _Default | None = option_field(
        (
            "A file extension or an iterable of extensions to use when "
            "discovering parquet files in a directory. Files that don't match "
            "these extensions will be ignored. `None` treats all files in the "
            "directory as parquet files."
        ),
        default=LIBRARY_DEFAULT,
        shown_default='`(".parq", ".parquet", ".pq")`',
    )
    dataset: Mapping[str, Any] | _Default | None = option_field(
        (
            "Dictionary of options to use when creating a "
            '`pyarrow.dataset.Dataset` object, e.g. `{"partitioning": '
            '{"flavor": "hive", "schema": ...}}`.'
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    read: Mapping[str, Any] | _Default | None = option_field(
        (
            "Dictionary of options to pass through to `engine.read_partitions` "
            "using the `read` key-word argument."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )
    arrow_to_pandas: Mapping[str, Any] | _Default | None = option_field(
        (
            "Dictionary of options to use when converting from `pyarrow.Table` "
            "to a pandas `DataFrame` object."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`",
    )


@dataclass(frozen=True, kw_only=True)
class CsvByDaskOptions(DaskOptions):
    """Dask's ``read_csv`` arguments, and pandas' it passes on, besides
    ``storage_options``: unset ones are left to Dask and pandas, but ``sep``
    (detected from the file's beginning) and, in the data browser,
    ``blocksize`` (half of ``max_whole_file_bytes``). The plugin's README
    lists them."""

    # Dask's own.
    blocksize: str | int | _Default | None = option_field(
        (
            "Number of bytes by which to cut up larger files. Default value is "
            "computed based on available physical memory and the number of "
            "cores, up to a maximum of 64MB. Can be a number like `64000000` or"
            ' a string like `"64MB"`. If `None`, a single block is used for '
            "each file."
        ),
        default=LIBRARY_DEFAULT,
        shown_default=(
            "computed, at most 64 MB; data browser: half of `max_whole_file_bytes`"
        ),
    )
    sample: int | _Default = option_field(
        "Number of bytes to use when determining dtypes.",
        default=LIBRARY_DEFAULT,
        shown_default="`256000`",
    )
    sample_rows: int | _Default = option_field(
        "Number of rows of the sample to use when determining dtypes.",
        default=LIBRARY_DEFAULT,
        shown_default="`10`",
    )
    enforce: bool | _Default = option_field(
        (
            "Whether to check that each partition's dtypes match those "
            "determined from the sample."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    assume_missing: bool | _Default = option_field(
        (
            "If True, all integer columns that aren't specified in `dtype` are "
            "assumed to contain missing values, and are converted to floats."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    include_path_column: bool | str | _Default = option_field(
        (
            "Whether or not to include the path to each particular file. If "
            "True a new column is added to the dataframe called `path`. If str,"
            " sets new column name."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    # pandas' read_csv's.
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
            "`(bad_line: list[str]) -> list[str] \\"
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
class JsonLinesByDaskOptions(DaskOptions):
    """Dask's ``read_json`` arguments for JSON Lines (``lines=True``), and
    pandas' it passes on, besides ``storage_options``: unset ones are left to
    Dask and pandas, but in the data browser ``blocksize`` (half of
    ``max_whole_file_bytes``). The plugin's README lists them."""

    # Dask's own.
    blocksize: int | _Default | None = option_field(
        (
            "If None, files are not blocked, and you get one partition per "
            "input file. If int, each partition will be approximately this size"
            " in bytes, to the nearest newline character."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`None`; data browser: half of `max_whole_file_bytes`",
    )
    sample: int | _Default = option_field(
        (
            "Number of bytes to pre-load, to provide an empty dataframe "
            "structure to any blocks without data. Only relevant when using "
            "blocksize."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`1048576`",
    )
    encoding: str | _Default = option_field(
        'The text encoding to implement, e.g. "utf-8".',
        default=LIBRARY_DEFAULT,
        shown_default="`'utf-8'`",
    )
    errors: str | _Default = option_field(
        "How to respond to errors in the conversion (see `str.encode()`).",
        default=LIBRARY_DEFAULT,
        shown_default="`'strict'`",
    )
    compression: str | _Default | None = option_field(
        "String like 'gzip' or 'xz'.",
        default=LIBRARY_DEFAULT,
        shown_default="`'infer'`",
    )
    include_path_column: bool | str | _Default = option_field(
        (
            "Include a column with the file path where each row in the "
            "dataframe originated. If `True`, a new column is added to the "
            "dataframe called `path`. If `str`, sets new column name."
        ),
        default=LIBRARY_DEFAULT,
        shown_default="`False`",
    )
    # pandas' read_json's.
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


def _unwrapped(fs: AbstractFileSystem, path: str) -> tuple[AbstractFileSystem, str]:
    """The filesystem a ``DirFileSystem`` wraps, and the path in it: Dask makes
    a folder's path absolute, which a ``DirFileSystem`` does not find, and
    fsspec cannot rebuild one from its ``storage_options``."""
    while isinstance(fs, DirFileSystem):
        path = fs._join(path)
        fs = fs.fs
    return fs, path


def _rebuilt_url(ctx: ItemContext) -> tuple[str, dict[str, Any]] | None:
    """The URL and ``storage_options`` from which fsspec makes a filesystem
    like the explorer's, for readers taking only a URL; None where it would
    not: one made with arguments by position, which ``storage_options``
    lacks, or of a class not registered for its protocol, which would come
    back as another.

    It makes no filesystem, and reads nothing. fsspec caches synchronous
    filesystems per thread, so in the view's worker thread asking for one
    would make another, e.g. connecting to an SFTP server again; the reader
    makes its own in any case."""
    fs, path = _unwrapped(ctx.fs, ctx.path)
    if getattr(fs, "storage_args", ()):
        return None
    url = fs.unstrip_protocol(path)
    try:
        registered = fsspec.get_filesystem_class(split_protocol(url)[0])
    except (ValueError, ImportError):
        return None
    return (url, dict(fs.storage_options)) if registered is type(fs) else None


def _code_kwargs(options: DaskOptions, defaults: Mapping[str, Any]) -> str:
    """The code's keyword arguments: the action's ``defaults``, then the
    options' arguments given, then ``storage_options``."""
    arguments = {**defaults, **options.code_arguments()}
    return format_arguments(arguments) + format_kwargs(
        storage_options=options.code_value("storage_options")
    )


# The code reading into a Dask DataFrame: {call}, the reader's call up to
# its keyword arguments, then {kwargs}.
_DASK_CODE = cleandoc("""
    import dask.dataframe as dd

    df = dd.{call}{kwargs})
    """)


def _dask_code(reader: str, url: str, kwargs: str) -> str:
    """The code reading ``url`` into a Dask DataFrame with ``reader``'s call,
    e.g. "read_parquet({url}"; ``kwargs`` and the closing parenthesis
    follow."""
    return _DASK_CODE.format(call=reader.format(url=repr(url)), kwargs=kwargs)


# Parquet files and folders, through the explorer's filesystem on every
# storage: a file's row groups are its partitions, a folder's files, with a
# partitioned folder's columns.


def _parquet_source(fmt: Parquet, ctx: ItemContext, url: str) -> str:
    """The item at ``url`` (or a path) as Dask reads it: a file as it is; a
    folder as the glob of its data files, in its partition folders. Given
    the folder itself, Dask reads it recursively, and fails on Spark's
    ``_temporary`` beside the partitions."""
    url = fmt.data_url(ctx, url)
    if ctx.is_dir and fmt.layout(ctx).files == "*":
        # Data files without an extension (Hive's): not "_SUCCESS" or ".crc"
        # checksums.
        url = url.removesuffix("*") + "[!_.]*"
    return url


@code(format=Parquet, engine=DaskEngine, label=AS_DATA_FRAME)
def parquet_as_data_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDaskOptions
) -> str:
    """The code reading the file, or the folder's data files, into a Dask
    DataFrame."""
    url = _parquet_source(fmt, ctx, ctx.url_or_local_path)
    return _dask_code("read_parquet({url}", url, _code_kwargs(options, {}))


@view(format=Parquet, engine=DaskEngine, code=parquet_as_data_frame)
def parquet_view(fmt: Parquet, ctx: ItemContext, options: ParquetByDaskOptions) -> View:
    """A DataFrame of the Parquet file, or of the folder's data files, which
    the data browser reads a partition at a time (the core's
    ``fetch_rows``). It takes no ``limits``: Dask reads only the partitions
    the data browser needs."""
    import dask.dataframe as dd

    arguments = options.arguments()
    defaults: dict[str, Any] = {}
    # A file's row groups, unless the user chose how to partition it.
    if not ctx.is_dir and not {"split_row_groups", "blocksize"} & arguments.keys():
        defaults["split_row_groups"] = True
    fs, path = _unwrapped(ctx.fs, ctx.path)
    data = dd.read_parquet(
        _parquet_source(fmt, ctx, path), filesystem=fs, **{**defaults, **arguments}
    )
    return QueryView(data=data)


# Text formats of files (CSV, JSON Lines), read in blocks: by URL with the
# explorer's storage_options where fsspec gives back the explorer's
# filesystem so, else from a copy on the kernel's disk.


def _text_view(
    reader: str,
    ctx: ItemContext,
    defaults: Mapping[str, Any],
    options: DaskOptions,
    limits: ViewLimits,
) -> View:
    """A DataFrame of the file read with ``dask.dataframe``'s ``reader``, in
    blocks of at most ``limits.max_whole_file_bytes`` bytes, unless
    ``blocksize`` says otherwise: ``defaults`` then the options are its
    arguments.

    Where fsspec cannot give back the explorer's filesystem by URL, the file
    is copied to the kernel's disk first: at once up to
    ``limits.max_whole_file_bytes``, after asking for a larger one."""
    import dask.dataframe as dd

    given = options.arguments()
    # Dask's blocks are one to two times the size asked for. A compressed
    # file is read whole: Dask cannot cut it into blocks, and warns unless
    # told so.
    compressed = given.get("compression", "infer") not in (None, "infer")
    blocksize = None if compressed else max(1, limits.max_whole_file_bytes // 2)
    blocks = {"blocksize": blocksize}
    arguments = {**blocks, **defaults, **given}
    read = getattr(dd, reader)
    log.debug("%s read in blocks of %s bytes", ctx.path, blocksize or "any")
    if isinstance(ctx.location, LocalLocation):
        return QueryView(data=read(ctx.url_or_local_path, **arguments))
    if (rebuilt := _rebuilt_url(ctx)) is not None:
        url, storage_options = rebuilt
        log.debug("%s read by Dask from its URL", ctx.path)
        return QueryView(data=read(url, storage_options=storage_options, **arguments))
    cache = local_file_cache()

    def copied() -> View:
        log.debug(
            "%s read by Dask from a copy on the kernel's disk: fsspec cannot "
            "make its filesystem from a URL",
            ctx.path,
        )
        path = cache.get(ctx).as_posix()
        try:
            view = QueryView(data=read(path, **arguments))
        except BaseException:
            cache.release(ctx.location, delay=_COPY_KEPT)
            raise
        view.on_close(lambda view: cache.release(ctx.location, delay=_COPY_KEPT))
        return view

    size = ctx.size
    if cache.status(ctx) == "cached" or (
        size is not None and size <= limits.max_whole_file_bytes
    ):
        return copied()
    size_text = f" ({format_size(size)})" if size else ""
    return ViewWithConfirmation(
        message=(
            f"Dask cannot reach this storage by URL: {ctx.name}{size_text} is "
            "copied to the kernel's disk first."
        ),
        factory=copied,
        button="Copy",
    )


@code(format=Csv, engine=DaskEngine, label=AS_DATA_FRAME)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByDaskOptions) -> str:
    """The code reading the file into a Dask DataFrame, with the separator
    detected."""
    sep = fmt.code_separator(ctx)
    defaults = {"sep": sep} if sep is not None else {}
    return _dask_code(
        "read_csv({url}", ctx.url_or_local_path, _code_kwargs(options, defaults)
    )


@view(format=Csv, engine=DaskEngine, code=csv_as_data_frame)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByDaskOptions, limits: ViewLimits
) -> View:
    """CSV in the data browser, the separator detected unless one is given."""
    defaults: dict[str, Any] = {}
    if options.sep is LIBRARY_DEFAULT:
        defaults["sep"] = fmt.separator(ctx.name, ctx.head_text(64 * 1024)[0])
    return _text_view("read_csv", ctx, defaults, options, limits)


@code(format=JsonLines, engine=DaskEngine, label=AS_DATA_FRAME)
def json_lines_as_data_frame(ctx: ItemContext, options: JsonLinesByDaskOptions) -> str:
    """The code reading the file into a Dask DataFrame."""
    return _dask_code(
        "read_json({url}, lines=True", ctx.url_or_local_path, _code_kwargs(options, {})
    )


@view(format=JsonLines, engine=DaskEngine, code=json_lines_as_data_frame)
def json_lines_view(
    ctx: ItemContext,
    options: JsonLinesByDaskOptions,
    limits: ViewLimits,
) -> View:
    """JSON Lines in the data browser."""
    return _text_view("read_json", ctx, {"lines": True}, options, limits)


# In the order tried; within a format, its view, then its code.
DASK_ACTIONS = register_actions(
    parquet_view,
    parquet_as_data_frame,
    csv_view,
    csv_as_data_frame,
    json_lines_view,
    json_lines_as_data_frame,
)
