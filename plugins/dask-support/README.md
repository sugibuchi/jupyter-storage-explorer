# jupyter-storage-explorer-dask-support

Dask support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
[Dask](https://www.dask.org/) DataFrames as an engine: the data browser on Parquet, CSV and JSON Lines, and code
loading them.

> **Experimental.** The plugin is tested with Dask's local schedulers only, not on a Dask cluster: it is not
> recommended for production use. Feedback is welcome, in this repository's
> [issues](https://github.com/sugibuchi/jupyter-storage-explorer/issues).

## Installation

```bash
pip install "jupyter-storage-explorer[dask]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[dask-support]"  # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them, as does `jupyter-storage-explorer-dask-support[full]`:

| Library | Needed for                                                                  |
|---------|-----------------------------------------------------------------------------|
| `dask`  | Mandatory: the engine, with its `dataframe` extra, which brings pandas and PyArrow |

The plugin is not in the explorer's `all` and `all-supports` extras: install it on purpose.

### Prerequisites

- Dask reads every storage through fsspec. The data browser reads through the explorer's filesystem, with the
  explorer's credentials: Dask needs no configuration.
- The data browser computes on the Dask scheduler active in the kernel. By default, it is Dask's threads.
- With a distributed `Client` active, the data browser runs its reads on the cluster. The explorer's filesystem, with
  its credentials, then goes to the workers, which must reach the storage. Local files and fsspec's memory filesystem
  are on the kernel's machine only. This setup is untested.
- The plugin never changes Dask's settings, such as its scheduler. Set them in the kernel as usual.

## How Dask reads your data

- A Parquet file's partitions are its row groups, and a folder's partitions are its files. Each page reads only the
  first partitions it needs.
- CSV and JSON Lines files are read in blocks of at most `max_whole_file_bytes`, 10 MB by default. Each page reads
  only the first blocks it needs.
- The data browser asks Dask for blocks of half that size, as Dask makes blocks of one to two times the size asked
  for. The `blocksize` [engine option](#engine-options) sets another size.
- A filter matching few rows, and a sort, read every partition.
- Dask guesses a CSV file's column types from its beginning. A later value of another type then fails the page. Set
  `dtype` or `assume_missing` in the engine options, or a larger `sample`.
- A CSV file whose quoted values hold line breaks cannot be cut into blocks. Set `blocksize` to `None` for such files.
- Some storages' filesystems cannot be given to Dask by URL. On those, the explorer first copies CSV and JSON Lines
  files to the kernel's disk.
  - Files up to `max_whole_file_bytes` are copied at once. For larger files, the explorer asks first.
  - A copy is kept for 10 minutes after its last view closes, and while the remote file is unchanged. The copies are
    deleted when the kernel exits.
- In memory mode, the data browser holds the rows as a pandas DataFrame.
- "Python code" reads the item by its URL, with fsspec's credentials from the environment or `storage_options`.

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    "s3://my-bucket/lake", plugin_options={"dask-support": {"priority": 10}}
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"dask-support": {"enabled": False}}
```

| Option     | Default | Meaning                                                                                                  |
|------------|---------|----------------------------------------------------------------------------------------------------------|
| `enabled`  | `True`  | Whether explorers use the plugin. `False`: not even imported.                                            |
| `priority` | lowest  | Plugins of a higher priority come first: their supports are tried before the others'. Equal ones by key. |

## Engine options

The supports' options, in `engine_options["dask"]` (by format, or `"*"` for all), for the data browser and the code:

```python
StorageExplorer(
    "s3://my-bucket/lake",
    engine_options={
        "dask": {
            "*": {"storage_options": {"anon": False}},
            "csv": {"dtype": {"zip": "string"}, "blocksize": "64MB"},
            "parquet": {"dtype_backend": "pyarrow"},
        },
    },
)
```

Every format takes:

| Option            | Default | Meaning                                                                                                                                                   |
|-------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `storage_options` | `None`  | Dask's `storage_options`, fsspec's keyword arguments, in the code. The data browser reads through the explorer's filesystem, with its own credentials. Keys that look like credentials are left out. |

The other options are each format's reader's arguments, of the same names, with their descriptions from Dask's and
pandas' API documentation. Those not set are not passed, so the libraries' defaults, shown below, apply, except where
the explorer sets its own. Values that are Python objects are used in the data browser but left out of the code, as
are options that look like credentials. Data types such as `np.float64` in `dtype` are such objects; strings such as
`"Int64"` are fine.

### Parquet (`parquet`)

`ParquetByDaskOptions`: the arguments of
[`dd.read_parquet`](https://docs.dask.org/en/stable/generated/dask.dataframe.read_parquet.html).

| Option                   | Default                                              | Meaning                                                                                                                                                                                                                                                                       |
|--------------------------|------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `columns`                | `None`                                               | Field name(s) to read in as columns in the output. By default all non-index fields will be read (as determined by the pandas parquet metadata, if present).                                                                                                                  |
| `filters`                | `None`                                               | List of filters to apply, like `[[('col1', '==', 0), ...], ...]`. Using this argument will result in row-wise filtering of the final partitions. Predicates can be expressed in disjunctive normal form (DNF).                                                                |
| `index`                  | `None`                                               | Field name(s) to use as the output frame index. By default will be inferred from the pandas parquet file metadata, if present. Use `False` to read all fields as columns.                                                                                                   |
| `categories`             | `None`                                               | For any fields listed here, if the parquet encoding is Dictionary, the column will be created with dtype category. Use only if it is guaranteed that the column is encoded as dictionary in all row-groups.                                                                 |
| `open_file_options`      | `None`                                               | Key/value arguments to be passed along to `AbstractFileSystem.open` when each parquet data file is open for reading. Experimental (optimized) "precaching" for remote file systems can be enabled by adding `{"method": "parquet"}` under the `"precache_options"` key.      |
| `dtype_backend`          | NumPy-backed                                         | Which dtype_backend to use, e.g. whether a DataFrame should have NumPy arrays, nullable dtypes are used for all dtypes that have a nullable implementation when `'numpy_nullable'` is set, pyarrow is used for all dtypes if `'pyarrow'` is set.                           |
| `calculate_divisions`    | `False`                                              | Whether to use min/max statistics from the footer metadata (or global `_metadata` file) to calculate divisions for the output DataFrame collection. May be extremely slow when no global `_metadata` file is present, especially when reading from remote storage.          |
| `ignore_metadata_file`   | `False`                                              | Whether to ignore the global `_metadata` file (when one is present).                                                                                                                                                                                                          |
| `metadata_task_size`     | configurable                                         | If parquet metadata is processed in parallel, the number of dataset files to be processed by each task in the Dask graph. `0` disables parallel metadata processing.                                                                                                        |
| `split_row_groups`       | `'infer'`; data browser: `True` for a file           | If True, then each output dataframe partition will correspond to a single parquet-file row-group. If False, each partition will correspond to a complete file. If a positive integer value is given, each dataframe partition will correspond to that number of parquet row-groups (or fewer). If `'adaptive'`, the metadata of each file will be used to ensure that every partition satisfies `blocksize`. |
| `blocksize`              | `'default'` (256 MiB)                                | The desired size of each output `DataFrame` partition in terms of total (uncompressed) parquet storage space. Ignored if `split_row_groups` is not set to `'infer'` or `'adaptive'`.                                                                                          |
| `aggregate_files`        | `None`                                               | Whether distinct file paths may be aggregated into the same output partition. Only used when `split_row_groups` is set to `'infer'`, `'adaptive'` or to an integer >1. For "hive-partitioned" datasets, a "partition"-column name can also be specified.                     |
| `parquet_file_extension` | `(".parq", ".parquet", ".pq")`; `None` for Hive's files | A file extension or an iterable of extensions to use when discovering parquet files in a directory. Files that don't match these extensions will be ignored. `None` treats all files in the directory as parquet files. The explorer passes `None` for folders of files named without an extension, as Hive's. |
| `dataset`                | `None`                                               | Dictionary of options to use when creating a `pyarrow.dataset.Dataset` object, e.g. `{"partitioning": {"flavor": "hive", "schema": ...}}`.                                                                                                                                  |
| `read`                   | `None`                                               | Dictionary of options to pass through to `engine.read_partitions` using the `read` key-word argument.                                                                                                                                                                       |
| `arrow_to_pandas`        | `None`                                               | Dictionary of options to use when converting from `pyarrow.Table` to a pandas `DataFrame` object.                                                                                                                                                                            |

### CSV (`csv`)

`CsvByDaskOptions`: the arguments of
[`dd.read_csv`](https://docs.dask.org/en/stable/generated/dask.dataframe.read_csv.html), and those of
[`pd.read_csv`](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html) that Dask passes on. Dask refuses
`index_col`, `nrows`, `iterator`, `chunksize` and `memory_map`, which are left out.

| Option                | Default                                           | Meaning                                                                                                                                                                                                                       |
|-----------------------|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `blocksize`           | computed, at most 64 MB; data browser: half of `max_whole_file_bytes` | Number of bytes by which to cut up larger files. Default value is computed based on available physical memory and the number of cores, up to a maximum of 64MB. Can be a number like `64000000` or a string like `"64MB"`. If `None`, a single block is used for each file. |
| `sample`              | `256000`                                          | Number of bytes to use when determining dtypes.                                                                                                                                                                              |
| `sample_rows`         | `10`                                              | Number of rows of the sample to use when determining dtypes.                                                                                                                                                                 |
| `enforce`             | `False`                                           | Whether to check that each partition's dtypes match those determined from the sample.                                                                                                                                       |
| `assume_missing`      | `False`                                           | If True, all integer columns that aren't specified in `dtype` are assumed to contain missing values, and are converted to floats.                                                                                           |
| `include_path_column` | `False`                                           | Whether or not to include the path to each particular file. If True a new column is added to the dataframe called `path`. If str, sets new column name.                                                                     |
| `sep` | detected | Character or regex pattern to treat as the delimiter. `sep=None` detects the separator from the first valid row of the file with Python's builtin sniffer tool, `csv.Sniffer`; it is supported only by the Python parsing engine, which will be used automatically. In addition, separators longer than 1 character and different from `'\s+'` will be interpreted as regular expressions and will also force the use of the Python parsing engine. Note that regex delimiters are prone to ignoring quoted data. Regex example: `'\r\t'`. |
| `header` | `'infer'` | Row number(s) containing column labels and marking the start of the data (zero-indexed). Default behavior is to infer the column names: if no `names` are passed the behavior is identical to `header=0` and column names are inferred from the first line of the file, if column names are passed explicitly to `names` then the behavior is identical to `header=None`. Explicitly pass `header=0` to be able to replace existing names. The header can be a list of integers that specify row locations for a `MultiIndex` on the columns e.g. `[0, 1, 3]`. Intervening rows that are not specified will be skipped (e.g. 2 in this example is skipped). Note that this parameter ignores commented lines and empty lines if `skip_blank_lines=True`, so `header=0` denotes the first line of data rather than the first line of the file.<br>When inferred from the file contents, headers are kept distinct from each other by renaming duplicate names with a numeric suffix of the form `".{count}"` starting from 1, e.g. `"foo"` and `"foo.1"`. Empty headers are named `"Unnamed: {i}"` or ` "Unnamed: {i}_level_{level}"` in the case of MultiIndex columns. |
| `names` | (none) | Sequence of column labels to apply. If the file contains a header row, then you should explicitly pass `header=0` to override the column names. Duplicates in this list are not allowed. |
| `usecols` | `None` | Subset of columns to select, denoted either by column labels or column indices. If list-like, all elements must either be positional (i.e. integer indices into the document columns) or strings that correspond to column names provided either by the user in `names` or inferred from the document header row(s). If `names` are given, the document header row(s) are not taken into account. For example, a valid list-like `usecols` parameter would be `[0, 1, 2]` or `['foo', 'bar', 'baz']`. Element order is ignored, so `usecols=[0, 1]` is the same as `[1, 0]`. To instantiate a `DataFrame` from `data` with element order preserved use `pd.read_csv(data, usecols=['foo', 'bar'])[['foo', 'bar']]` for columns in `['foo', 'bar']` order or `pd.read_csv(data, usecols=['foo', 'bar'])[['bar', 'foo']]` for `['bar', 'foo']` order.<br>If callable, the callable function will be evaluated against the column names, returning names where the callable function evaluates to `True`. An example of a valid callable argument would be `lambda x: x.upper() in ['AAA', 'BBB', 'DDD']`. Using this parameter results in much faster parsing time and lower memory usage. |
| `dtype` | `None` | Data type(s) to apply to either the whole dataset or individual columns. E.g., `{'a': np.float64, 'b': np.int32, 'c': 'Int64'}` Use `str` or `object` together with suitable `na_values` settings to preserve and not interpret `dtype`. If `converters` are specified, they will be applied INSTEAD of `dtype` conversion. Specify a `defaultdict` as input where the default determines the `dtype` of the columns which are not explicitly listed. |
| `engine` | `None` | Parser engine to use. The C and pyarrow engines are faster, while the python engine is currently more feature-complete. Multithreading is currently only supported by the pyarrow engine. Some features of the "pyarrow" engine are unsupported or may not work correctly. |
| `true_values` | `None` | Values to consider as `True` in addition to case-insensitive variants of 'True'. |
| `false_values` | `None` | Values to consider as `False` in addition to case-insensitive variants of 'False'. |
| `skipinitialspace` | `False` | Skip spaces after delimiter. |
| `skiprows` | `None` | Line numbers to skip (0-indexed) or number of lines to skip (`int`) at the start of the file.<br>If callable, the callable function will be evaluated against the row indices, returning `True` if the row should be skipped and `False` otherwise. An example of a valid callable argument would be `lambda x: x in [0, 2]`. |
| `skipfooter` | `0` | Number of lines at bottom of file to skip (Unsupported with `engine='c'`). |
| `na_values` | `None` | Additional strings to recognize as `NA`/`NaN`. If `dict` passed, specific per-column `NA` values.  By default the following values are interpreted as `NaN`: empty string, "NaN", "N/A", "NULL", and other common representations of missing data. |
| `keep_default_na` | `True` | Whether or not to include the default `NaN` values when parsing the data. Depending on whether `na_values` is passed in, the behavior is as follows:<br>• If `keep_default_na` is `True`, and `na_values` are specified, `na_values` is appended to the default `NaN` values used for parsing.<br>• If `keep_default_na` is `True`, and `na_values` are not specified, only the default `NaN` values are used for parsing.<br>• If `keep_default_na` is `False`, and `na_values` are specified, only the `NaN` values specified `na_values` are used for parsing.<br>• If `keep_default_na` is `False`, and `na_values` are not specified, no strings will be parsed as `NaN`.<br>Note that if `na_filter` is passed in as `False`, the `keep_default_na` and `na_values` parameters will be ignored. |
| `na_filter` | `True` | Detect missing value markers (empty strings and the value of `na_values`). In data without any `NA` values, passing `na_filter=False` can improve the performance of reading a large file. |
| `skip_blank_lines` | `True` | If `True`, skip over blank lines rather than interpreting as `NaN` values. |
| `parse_dates` | `None` | The behavior is as follows:<br>• `bool`. If `True` -> try parsing the index.<br>• `None`. Behaves like `True` if `date_format` is specified.<br>• `list` of `int` or names. e.g. If `[1, 2, 3]` -> try parsing columns 1, 2, 3 each as a separate date column.<br>If a column or index cannot be represented as an array of `datetime`, say because of an unparsable value or a mixture of timezones, the column or index will be returned unaltered as an `object` data type. For non-standard `datetime` parsing, use `to_datetime` after `read_csv`.<br>Note: A fast-path exists for iso8601-formatted dates. |
| `date_format` | `None` | Format to use for parsing dates and/or times when used in conjunction with `parse_dates`. The strftime to parse time, e.g. `"%d/%m/%Y"`. See [strftime documentation](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior) for more information on choices, though note that `"%f"` will parse all the way up to nanoseconds. You can also pass:<br>• "ISO8601", to parse any [ISO8601](https://en.wikipedia.org/wiki/ISO_8601) time string (not necessarily in exactly the same format);<br>• "mixed", to infer the format for each element individually. This is risky, and you should probably use it along with `dayfirst`. |
| `dayfirst` | `False` | DD/MM format dates, international and European format. |
| `cache_dates` | `True` | If `True`, use a cache of unique, converted dates to apply the `datetime` conversion. May produce significant speed-up when parsing duplicate date strings, especially ones with timezone offsets. |
| `compression` | `'infer'` | For on-the-fly decompression of on-disk data. If 'infer' and 'filepath_or_buffer' is path-like, then detect compression from the following extensions: '.gz', '.bz2', '.zip', '.xz', '.zst', '.tar', '.tar.gz', '.tar.xz' or '.tar.bz2' (otherwise no compression). If using 'zip' or 'tar', the ZIP file must contain only one data file to be read in. Set to `None` for no decompression. Can also be a dict with key `'method'` set to one of {`'zip'`, `'gzip'`, `'bz2'`, `'zstd'`, `'xz'`, `'tar'`} and other key-value pairs are forwarded to `zipfile.ZipFile`, `gzip.GzipFile`, `bz2.BZ2File`, `zstandard.ZstdDecompressor`, `lzma.LZMAFile` or `tarfile.TarFile`, respectively. As an example, the following could be passed for Zstandard decompression using a custom compression dictionary: `compression={'method': 'zstd', 'dict_data': my_compression_dict}`. |
| `thousands` | `None` | Character acting as the thousands separator in numerical values. |
| `decimal` | `'.'` | Character to recognize as decimal point (e.g., use ',' for European data). |
| `lineterminator` | `None` | Character used to denote a line break. Only valid with C parser. |
| `quotechar` | `'"'` | Character used to denote the start and end of a quoted item. Quoted items can include the `delimiter` and it will be ignored. |
| `quoting` | `0` | Control field quoting behavior per `csv.QUOTE_*` constants: 0 (`QUOTE_MINIMAL`, the default: only fields containing special characters are quoted, e.g. characters defined in `quotechar`, `delimiter`, or `lineterminator`), 1 (`QUOTE_ALL`), 2 (`QUOTE_NONNUMERIC`) or 3 (`QUOTE_NONE`). |
| `doublequote` | `True` | When `quotechar` is specified and `quoting` is not `QUOTE_NONE`, indicate whether or not to interpret two consecutive `quotechar` elements INSIDE a field as a single `quotechar` element. |
| `escapechar` | `None` | Character used to escape other characters. |
| `comment` | `None` | Character indicating that the remainder of line should not be parsed. If found at the beginning of a line, the line will be ignored altogether. This parameter must be a single character. Like empty lines (as long as `skip_blank_lines=True`), fully commented lines are ignored by the parameter `header` but not by `skiprows`. For example, if `comment='#'`, parsing `#empty\na,b,c\n1,2,3` with `header=0` will result in `'a,b,c'` being treated as the header. |
| `encoding` | `None` | Encoding to use for UTF when reading/writing (ex. `'utf-8'`). [List of Python standard encodings](https://docs.python.org/3/library/codecs.html#standard-encodings) . |
| `encoding_errors` | `'strict'` | How encoding errors are treated. [List of possible values](https://docs.python.org/3/library/codecs.html#error-handlers) . |
| `on_bad_lines` | `'error'`                                       | Specifies what to do upon encountering a bad line (a line with too many fields). Allowed values are:<br>• `'error'`, raise an Exception when a bad line is encountered.<br>• `'warn'`, raise a warning when a bad line is encountered and skip that line.<br>• `'skip'`, skip bad lines without raising or warning when they are encountered.<br>• Callable, function that will process a single bad line.<br>• With `engine='python'`, function with signature `(bad_line: list[str]) -> list[str] \ | None`. `bad_line` is a list of strings split by the `sep`. If the function returns `None`, the bad line will be ignored. If the function returns a new `list` of strings with more elements than expected, a `ParserWarning` will be emitted while dropping extra elements.<br>• With `engine='pyarrow'`, function with signature as described in pyarrow documentation: [invalid_row_handler](https://arrow.apache.org/docs/python/generated/pyarrow.csv.ParseOptions.html#pyarrow.csv.ParseOptions.invalid_row_handler). |
| `low_memory` | `True` | Internally process the file in chunks, resulting in lower memory use while parsing, but possibly mixed type inference.  To ensure no mixed types either set `False`, or specify the type with the `dtype` parameter. Note that the entire file is read into a single `DataFrame` regardless, use the `chunksize` or `iterator` parameter to return the data in chunks. (Only valid with C parser). |
| `dtype_backend` | (none) | Back-end data type applied to the resultant `DataFrame` (still experimental). If not specified, the default behavior is to not use nullable data types. If specified, the behavior is as follows:<br>• `"numpy_nullable"`: returns nullable-dtype-backed `DataFrame`<br>• `"pyarrow"`: returns pyarrow-backed nullable `ArrowDtype` `DataFrame` |

### JSON Lines (`json-lines`)

`JsonLinesByDaskOptions`: the arguments of
[`dd.read_json`](https://docs.dask.org/en/stable/generated/dask.dataframe.read_json.html), with `lines=True`, and
those of [`pd.read_json`](https://pandas.pydata.org/docs/reference/api/pandas.read_json.html) that Dask passes on.
`nrows` and `engine` are left out: Dask applies them to each block, and its blocks take no `engine="pyarrow"`.

| Option                | Default                                       | Meaning                                                                                                                                                                                        |
|-----------------------|-----------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `blocksize`           | `None`; data browser: half of `max_whole_file_bytes` | If None, files are not blocked, and you get one partition per input file. If int, each partition will be approximately this size in bytes, to the nearest newline character.                  |
| `sample`              | `1048576`                                     | Number of bytes to pre-load, to provide an empty dataframe structure to any blocks without data. Only relevant when using blocksize.                                                         |
| `encoding`            | `'utf-8'`                                     | The text encoding to implement, e.g. "utf-8".                                                                                                                                                  |
| `errors`              | `'strict'`                                    | How to respond to errors in the conversion (see `str.encode()`).                                                                                                                              |
| `compression`         | `'infer'`                                     | String like 'gzip' or 'xz'.                                                                                                                                                                    |
| `include_path_column` | `False`                                       | Include a column with the file path where each row in the dataframe originated. If `True`, a new column is added to the dataframe called `path`. If `str`, sets new column name.             |
| `dtype` | `None` | If True, infer dtypes; if a dict of column to dtype, then use those; if False, then don't infer dtypes at all, applies only to the data.<br>For all `orient` values except `'table'`, default is True. |
| `convert_axes` | `None` | Try to convert the axes to the proper dtypes.<br>For all `orient` values except `'table'`, default is True. |
| `convert_dates` | `True` | If True then default datelike columns may be converted (depending on keep_default_dates). If False, no dates will be converted. If a list of column names, then those columns will be converted and default datelike columns may also be converted (depending on keep_default_dates). |
| `keep_default_dates` | `True` | If parsing dates (convert_dates is not False), then try to parse the default datelike columns. A column label is datelike if<br>• it ends with `'_at'`,<br>• it ends with `'_time'`,<br>• it begins with `'timestamp'`,<br>• it is `'modified'`, or<br>• it is `'date'`. |
| `precise_float` | `False` | Set to enable usage of higher precision (strtod) function when decoding string to double values. Default (False) is to use fast but less precise builtin functionality. |
| `date_unit` | `None` | The timestamp unit to detect if converting dates. The default behaviour is to try and detect the correct precision, but if this is not desired then pass one of 's', 'ms', 'us' or 'ns' to force parsing only seconds, milliseconds, microseconds or nanoseconds respectively. |
| `dtype_backend` | (none) | Back-end data type applied to the resultant `DataFrame` (still experimental). If not specified, the default behavior is to not use nullable data types. If specified, the behavior is as follows:<br>• `"numpy_nullable"`: returns nullable-dtype-backed `DataFrame`<br>• `"pyarrow"`: returns pyarrow-backed nullable `ArrowDtype` `DataFrame` |
