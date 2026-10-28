# jupyter-storage-explorer-polars-support

Polars support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
Polars as an engine: the data browser on Delta Lake tables, Parquet, CSV, JSON Lines and Excel, and code loading them.

## Installation

```bash
pip install "jupyter-storage-explorer[polars]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[polars-support]"  # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them, as does `jupyter-storage-explorer-polars-support[full]`:

| Library     | Needed for                                 |
|-------------|--------------------------------------------|
| `polars`    | Mandatory: the engine                      |
| `deltalake` | Delta Lake tables                          |
| `fastexcel` | Excel workbooks, read by polars' `calamine` |
| `pyarrow`   | Parquet on storages polars cannot read itself |

Without `deltalake`, `fastexcel` or `pyarrow`, the other formats still work.

### Prerequisites

- polars needs credentials for cloud storage: see [Authentication](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/polars-support/README.md#authentication).

### Authentication

polars and deltalake read cloud storage themselves, not through the explorer's fsspec filesystems. So they need
credentials of their own, besides those of fsspec.

We recommend configuring them with polars'
[credential providers](https://docs.pola.rs/user-guide/io/cloud-storage/), one per storage with `by_protocol`:

```python
import polars as pl
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.engine import by_protocol

StorageExplorer(
    filesystems={
        "Lake": "abfs://lake@account.dfs.core.windows.net",
        "Personal": "s3://my-bucket",
    },
    engine_options={
        "polars": {
            "*": by_protocol(
                {
                    "abfs": {"credential_provider": pl.CredentialProviderAzure()},
                    "s3": {
                        "credential_provider": pl.CredentialProviderAWS(
                            profile_name="personal"
                        )
                    },
                }
            ),
        },
    },
)
```

polars has these credential providers:

- [`pl.CredentialProviderAWS`](https://docs.pola.rs/api/python/stable/reference/api/polars.CredentialProviderAWS.html):
  S3, e.g. with an AWS profile.
- [`pl.CredentialProviderAzure`](https://docs.pola.rs/api/python/stable/reference/api/polars.CredentialProviderAzure.html):
  Azure Storage, e.g. with a credential from azure-identity.
- [`pl.CredentialProviderGCP`](https://docs.pola.rs/api/python/stable/reference/api/polars.CredentialProviderGCP.html):
  Google Cloud Storage.

For the launcher's tabs, `engine_options()` in `launcher.py` returns the same engine options:

```python
def engine_options():
    return {
        "polars": {
            "*": by_protocol(
                {
                    "abfs": {"credential_provider": pl.CredentialProviderAzure()},
                }
            ),
        },
    }
```

Instead of engine options, you can configure the environment variables of object_store, the library polars reads
cloud storage with. See its keys for
[AWS](https://docs.rs/object_store/latest/object_store/aws/enum.AmazonS3ConfigKey.html),
[Azure](https://docs.rs/object_store/latest/object_store/azure/enum.AzureConfigKey.html) and
[GCP](https://docs.rs/object_store/latest/object_store/gcp/enum.GoogleConfigKey.html).

### Limitations

polars reads lazily only the storages its own readers reach: local disks, S3, Google Cloud Storage, Azure, HTTP(S) and
Hugging Face. On other storages, such as SFTP, the explorer reads through fsspec:

- CSV and JSON Lines files are read into memory. For files over `max_whole_file_bytes`, 10 MB by default, you choose
  between the whole file and its first 10 MB.
- Parquet files and folders are read lazily as PyArrow datasets, in the data browser and in "Python code". The Parquet
  [engine options](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/polars-support/README.md#engine-options) do not apply.
- Delta Lake tables cannot be viewed.
- "Python code" reads other files whole into a DataFrame, never a LazyFrame. Other folders and Delta Lake tables get no
  code.

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    "s3://my-bucket/lake", plugin_options={"polars-support": {"priority": 10}}
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"polars-support": {"enabled": False}}
```

<!-- options: jupyter_storage_explorer.StorageExplorerPluginOptions -->
| Option     | Default | Meaning                                                                                                                         |
|------------|---------|---------------------------------------------------------------------------------------------------------------------------------|
| `enabled`  | `True`  | Whether explorers use the plugin. `False`: not even imported.                                                                   |
| `priority` | lowest  | Plugins of a higher priority come first: their actions, operations and mappers are tried before the others'. Equal ones by key. |

## Engine options

The plugin's options, in `engine_options["polars"]` (by format, or `"*"` for all), for the data browser and the code:

```python
StorageExplorer(
    "s3://my-bucket/lake",
    engine_options={
        "polars": {
            "csv": {"null_values": ["NA"], "try_parse_dates": True},
            "delta": {"version": 3},
        },
    },
)
```

Every format but JSON and Excel takes:

<!-- options: jupyter_storage_explorer_polars_support.PolarsOptions -->
| Option                | Default  | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
|-----------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `storage_options`     | `None`   | polars' `storage_options`: object_store's keys, not fsspec's ([AWS](https://docs.rs/object_store/latest/object_store/aws/enum.AmazonS3ConfigKey.html), [GCP](https://docs.rs/object_store/latest/object_store/gcp/enum.GoogleConfigKey.html), [Azure](https://docs.rs/object_store/latest/object_store/azure/enum.AzureConfigKey.html); Delta Lake's are [delta-rs'](https://delta-io.github.io/delta-rs/latest/usage/loading-table/)). Without them, polars reads credentials from the environment. |
| `credential_provider` | `"auto"` | polars' `credential_provider`: a function giving cloud storage credentials; see [Authentication](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/plugins/polars-support/README.md#authentication).                                                                                                                                                                                                                                                                                   |

Every format takes:

<!-- options: jupyter_storage_explorer_polars_support.FsspecCodeOptions -->
| Option                   | Default | Meaning                                                                                                                                                                                                   |
|--------------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `fsspec_storage_options` | `None`  | `fsspec.open`'s keyword arguments in the code that opens the file with fsspec: Excel's code, and the other formats' on storages polars cannot read itself. Those that look like credentials are left out. |

The other options are each format's reader's arguments, of the same names, with their descriptions from polars' API
documentation. Those not set are not passed, so polars' defaults, shown below, apply, except where the explorer sets
its own.

### CSV (`csv`)

`CsvByPolarsOptions`: the arguments of
[`pl.scan_csv`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_csv.html).

<!-- options: jupyter_storage_explorer_polars_support.CsvByPolarsOptions -->
| Option                   | Default                       | Meaning                                                                                                                                                                                                                                                                                                           |
|--------------------------|-------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `has_header`             | `True`                        | Indicate if the first row of the dataset is a header or not. If set to False, column names will be autogenerated in the following format: `column_x`, with `x` being an enumeration over every column in the dataset, starting at 0.                                                                              |
| `separator`              | detected                      | Single byte character to use as separator in the file.                                                                                                                                                                                                                                                            |
| `comment_prefix`         | `None`                        | A string used to indicate the start of a comment line. Comment lines are skipped during parsing. Common examples of comment prefixes are `#` and `//`.                                                                                                                                                            |
| `quote_char`             | `'"'`                         | Single byte character used for csv quoting, default = `"`. Set to None to turn off special handling and escaping of quotes.                                                                                                                                                                                       |
| `skip_rows`              | `0`                           | Start reading after `skip_rows` rows. The header will be parsed at this offset. Note that we respect CSV escaping/comments when skipping rows. If you want to skip by newline char only, use `skip_lines`.                                                                                                        |
| `skip_lines`             | `0`                           | Start reading after `skip_lines` lines. The header will be parsed at this offset. Note that CSV escaping will not be respected when skipping lines. If you want to skip valid CSV rows, use `skip_rows`.                                                                                                          |
| `schema`                 | `None`                        | Provide the schema. This means that polars doesn't do schema inference. This argument expects the complete schema, whereas `schema_overrides` can be used to partially overwrite a schema. Note that the order of the columns in the provided `schema` must match the order of the columns in the CSV being read. |
| `schema_overrides`       | `None`                        | Overwrite dtypes during inference; should be a {colname:dtype,} dict or, if providing a list of strings to `new_columns`, a list of dtypes of the same length.                                                                                                                                                    |
| `null_values`            | `None`                        | Values to interpret as null values. You can provide a:<br>• `str`: All values equal to this string will be null.<br>• `List[str]`: All values equal to any string in this list will be null.<br>• `Dict[str, str]`: A dictionary that maps column name to a null value string.                                    |
| `empty_string_is_null`   | `True`                        | By default a missing string value is considered to be null. If `empty_string_is_null` is set to False, missing string values are considered to decoded as empty strings.                                                                                                                                          |
| `ignore_errors`          | `False`                       | Try to keep reading lines if some lines yield errors. First try `infer_schema=False` to read all columns as `pl.String` to check which values might cause an issue.                                                                                                                                               |
| `infer_schema`           | `True`                        | When `True`, the schema is inferred from the data using the first `infer_schema_length` rows. When `False`, the schema is not inferred and will be `pl.String` if not specified in `schema` or `schema_overrides`.                                                                                                |
| `infer_schema_length`    | `100`                         | The maximum number of rows to scan for schema inference. This applies individually to each file included according to `infer_schema_files`. If set to `None`, the full data will be scanned into memory **(this is slow)**. Alternatively set `infer_schema=False` to read all columns as `pl.String`.            |
| `infer_schema_files`     | `10`                          | How many files to use when inferring schema.<br>*Unstable* in polars: it may change at any time.                                                                                                                                                                                                                  |
| `n_rows`                 | `None`                        | Stop reading from CSV file after reading `n_rows`.                                                                                                                                                                                                                                                                |
| `encoding`               | `'utf8'`                      | Lossy means that invalid utf8 values are replaced with `�` characters. Defaults to "utf8".                                                                                                                                                                                                                        |
| `low_memory`             | `False`                       | Reduce memory pressure at the expense of performance.                                                                                                                                                                                                                                                             |
| `skip_rows_after_header` | `0`                           | Skip this number of rows when the header is parsed.                                                                                                                                                                                                                                                               |
| `row_index_name`         | `None`                        | If not None, this will insert a row index column with the given name into the DataFrame.                                                                                                                                                                                                                          |
| `row_index_offset`       | `0`                           | Offset to start the row index column (only used if the name is set).                                                                                                                                                                                                                                              |
| `try_parse_dates`        | `False`; data browser: `True` | Try to automatically parse dates. Most ISO8601-like formats can be inferred, as well as a handful of others. If this does not succeed, the column remains of data type `pl.String`.                                                                                                                               |
| `eol_char`               | `'\n'`                        | Single byte end of line character (default: `\n`). When encountering a file with windows line endings (`\r\n`), one can go with the default `\n`. The extra `\r` will be removed when processed.                                                                                                                  |
| `new_columns`            | `None`                        | Provide an explicit list of string column names to use (for example, when scanning a headerless CSV file). If the given list is shorter than the width of the DataFrame the remaining columns will have their original name.                                                                                      |
| `truncate_ragged_lines`  | `None`; data browser: `True`  | Truncate lines that are longer than the schema.                                                                                                                                                                                                                                                                   |
| `raise_if_empty`         | `None`                        | Control behavior when scanning empty files:<br>• `True`: Raise a `NoDataError`.<br>• `False`: Return 0 rows.<br>This defaults to `False` if `has_header=False` and a `schema` is specified, and `True` otherwise.                                                                                                 |
| `decimal_comma`          | `False`                       | Parse floats using a comma as the decimal separator instead of a period.                                                                                                                                                                                                                                          |
| `glob`                   | `True`                        | Expand path given via globbing rules.                                                                                                                                                                                                                                                                             |
| `include_file_paths`     | `None`                        | Include the path of the source file(s) as a column with this name.                                                                                                                                                                                                                                                |
| `extra_columns`          | `None`                        | Configuration for behavior when extra columns outside of the defined schema are encountered in the data:<br>• `ignore`: Silently ignores.<br>• `raise`: Raises an error.<br>*Unstable* in polars: it may change at any time.                                                                                      |
| `missing_columns`        | `None`                        | Configuration for behavior when columns defined in the schema are missing from the data:<br>• `"insert"`: Insert the missing columns with NULL values.<br>• `"raise"`: Raise an error.<br>*Unstable* in polars: it may change at any time.                                                                        |

### JSON Lines (`json-lines`)

`JsonLinesByPolarsOptions`: the arguments of
[`pl.scan_ndjson`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_ndjson.html).

<!-- options: jupyter_storage_explorer_polars_support.JsonLinesByPolarsOptions -->
| Option                | Default | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
|-----------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `schema`              | `None`  | The DataFrame schema may be declared in several ways:<br>• As a dict of {name:type} pairs; if type is None, it will be auto-inferred.<br>• As a list of column names; in this case types are automatically inferred.<br>• As a list of (name,type) pairs; this is equivalent to the dictionary form.<br>If you supply a list of column names that does not match the names in the underlying data, the names given here will overwrite them. The number of names given in the schema should match the underlying data dimensions. |
| `schema_overrides`    | `None`  | Support type specification or override of one or more columns; note that any dtypes inferred from the schema param will be overridden.                                                                                                                                                                                                                                                                                                                                                                                            |
| `infer_schema_length` | `100`   | The maximum number of rows to scan for schema inference. If set to `None`, the full data may be scanned *(this is slow)*.                                                                                                                                                                                                                                                                                                                                                                                                         |
| `batch_size`          | `1024`  | Number of rows to read in each batch.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `n_rows`              | `None`  | Stop reading from JSON file after reading `n_rows`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `low_memory`          | `False` | Reduce memory pressure at the expense of performance.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `row_index_name`      | `None`  | If not None, this will insert a row index column with give name into the DataFrame                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `row_index_offset`    | `0`     | Offset to start the row index column (only use if the name is set)                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `ignore_errors`       | `False` | Return `Null` if parsing fails because of schema mismatches.                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `include_file_paths`  | `None`  | Include the path of the source file(s) as a column with this name.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

### JSON (`json`)

`JsonByPolarsOptions`: the arguments of
[`pl.read_json`](https://docs.pola.rs/api/python/stable/reference/api/polars.read_json.html).

<!-- options: jupyter_storage_explorer_polars_support.JsonByPolarsOptions -->
| Option                | Default | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
|-----------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `schema`              | `None`  | The DataFrame schema may be declared in several ways:<br>• As a dict of {name:type} pairs; if type is None, it will be auto-inferred.<br>• As a list of column names; in this case types are automatically inferred.<br>• As a list of (name,type) pairs; this is equivalent to the dictionary form.<br>If you supply a list of column names that does not match the names in the underlying data, the names given here will overwrite them. The number of names given in the schema should match the underlying data dimensions. |
| `schema_overrides`    | `None`  | Support type specification or override of one or more columns; note that any dtypes inferred from the schema param will be overridden.                                                                                                                                                                                                                                                                                                                                                                                            |
| `infer_schema_length` | `100`   | The maximum number of rows to scan for schema inference. If set to `None`, the full data may be scanned *(this is slow)*.                                                                                                                                                                                                                                                                                                                                                                                                         |

### Parquet (`parquet`)

`ParquetByPolarsOptions`: the arguments of
[`pl.scan_parquet`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_parquet.html).

<!-- options: jupyter_storage_explorer_polars_support.ParquetByPolarsOptions -->
| Option                 | Default                            | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|------------------------|------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `n_rows`               | `None`                             | Stop reading from parquet file after reading `n_rows`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `row_index_name`       | `None`                             | If not None, this will insert a row index column with the given name into the DataFrame                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `row_index_offset`     | `0`                                | Offset to start the row index column (only used if the name is set)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `parallel`             | `'auto'`                           | This determines the direction and strategy of parallelism. 'auto' will try to determine the optimal direction.<br>The `prefiltered` strategy first evaluates the pushed-down predicates in parallel and determines a mask of which rows to read. Then, it parallelizes over both the columns and the row groups while filtering out rows that do not need to be read. This can provide significant speedups for large files (i.e. many row-groups) with a predicate that filters clustered rows or filters heavily. In other cases, `prefiltered` may slow down the scan compared other strategies.<br>The `prefiltered` settings falls back to `auto` if no predicate is given.<br>The `prefiltered` strategy is *unstable* in polars: it may change at any time. |
| `use_statistics`       | `True`                             | Use statistics in the parquet to determine if pages can be skipped from reading.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `hive_partitioning`    | by the folders detected            | Infer statistics and schema from hive partitioned URL and use them to prune reads.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `glob`                 | `True`                             | Expand path given via globbing rules.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `hidden_file_prefix`   | `None`; data browser: `['.', '_']` | Skip reading files whose names begin with the specified prefixes.<br>*Unstable* in polars: it may change at any time.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `schema`               | `None`                             | Specify the datatypes of the columns. The datatypes must match the datatypes in the file(s). If there are extra columns that are not in the file(s), consider also passing `missing_columns='insert'`.<br>*Unstable* in polars: it may change at any time.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `hive_schema`          | `None`                             | The column names and data types of the columns by which the data is partitioned. If set to `None` (default), the schema of the Hive partitions is inferred.<br>*Unstable* in polars: it may change at any time.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `try_parse_hive_dates` | `True`                             | Whether to try parsing hive values as date/datetime types.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `low_memory`           | `False`                            | Reduce memory pressure at the expense of performance.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `cache`                | `True`                             | Cache the result after reading.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `include_file_paths`   | `None`                             | Include the path of the source file(s) as a column with this name.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `missing_columns`      | `'raise'`                          | Configuration for behavior when columns defined in the schema are missing from the data:<br>• `insert`: Inserts the missing columns using NULLs as the row values.<br>• `raise`: Raises an error.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `extra_columns`        | `'raise'`                          | Configuration for behavior when extra columns outside of the defined schema are encountered in the data:<br>• `ignore`: Silently ignores.<br>• `raise`: Raises an error.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

### Excel (`excel`)

`ExcelByPolarsOptions`: the arguments of
[`pl.read_excel`](https://docs.pola.rs/api/python/stable/reference/api/polars.read_excel.html). The data browser
shows a workbook's sheets on tabs below the table (only one sheet: that one), each read when chosen; with
`sheet_id`, `sheet_name` or `table_name`, the sheet or table they give (several: on tabs).

<!-- options: jupyter_storage_explorer_polars_support.ExcelByPolarsOptions -->
| Option                | Default      | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
|-----------------------|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `sheet_id`            | `None`       | Sheet number(s) to convert (set `0` to load all sheets as DataFrames) and return a `{sheetname:frame,}` dict. (Defaults to `1` if neither this nor `sheet_name` are specified). Can also take a sequence of sheet numbers.                                                                                                                                                                                                                                                                                                                                                                                                          |
| `sheet_name`          | `None`       | Sheet name(s) to convert; cannot be used in conjunction with `sheet_id`. If more than one is given then a `{sheetname:frame,}` dict is returned.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `table_name`          | `None`       | Name of a specific table to read; note that table names are unique across the workbook, so additionally specifying a sheet id or name is optional; if one of those parameters *is* specified, an error will be raised if the named table is not found in that particular sheet.                                                                                                                                                                                                                                                                                                                                                     |
| `engine`              | `'calamine'` | Library used to parse the spreadsheet file; defaults to "calamine".<br>• "calamine": this engine can be used for reading all major types of Excel Workbook (`.xlsx`, `.xlsb`, `.xls`) and is dramatically faster than the other options, using the `fastexcel` module to bind the Rust-based Calamine parser.<br>• "openpyxl": this engine is significantly slower than both `calamine` and `xlsx2csv`, but can provide a useful fallback if you are otherwise unable to read data from your workbook.<br>• "xlsx2csv": converts the data to an in-memory CSV before using the native polars `read_csv` method to parse the result. |
| `engine_options`      | `None`       | Additional options passed to the underlying engine's primary parsing constructor (given below), if supported:<br>• "calamine": n/a (can only provide `read_options`)<br>• "openpyxl": [load_workbook](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html#openpyxl.reader.excel.load_workbook)<br>• "xlsx2csv": [Xlsx2csv](https://github.com/dilshod/xlsx2csv/blob/f35734aa453d65102198a77e7b8cd04928e6b3a2/xlsx2csv.py#L157)                                                                                                                                                                                 |
| `read_options`        | `None`       | Options passed to the underlying engine method that reads the sheet data. Where supported, this allows for additional control over parsing. The specific read methods associated with each engine are:<br>• "calamine": [load_sheet_by_name](https://fastexcel.toucantoco.dev/fastexcel.html#ExcelReader.load_sheet_by_name) (or [load_table](https://fastexcel.toucantoco.dev/fastexcel.html#ExcelReader.load_table) if using the `table_name` parameter).<br>• "openpyxl": n/a (can only provide `engine_options`)<br>• "xlsx2csv": see `read_csv`                                                                                |
| `has_header`          | `True`       | Indicate if the first row of the table data is a header or not. If False, column names will be autogenerated in the following format: `column_x`, with `x` being an enumeration over every column in the dataset, starting at 0.                                                                                                                                                                                                                                                                                                                                                                                                    |
| `columns`             | `None`       | Columns to read from the sheet; if not specified, all columns are read. Can be given as a sequence of column names or indices, or a single column name.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `schema_overrides`    | `None`       | Support type specification or override of one or more columns.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `infer_schema_length` | `100`        | The maximum number of rows to scan for schema inference. If set to `None`, the entire dataset is scanned to determine the dtypes, which can slow parsing for large workbooks. Note that only the "calamine" and "xlsx2csv" engines support this parameter.                                                                                                                                                                                                                                                                                                                                                                          |
| `include_file_paths`  | `None`       | Include the path of the source file(s) as a column with this name.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `drop_empty_rows`     | `True`       | Indicate whether to omit empty rows when reading data into the DataFrame.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `drop_empty_cols`     | `True`       | Indicate whether to omit empty columns (with no headers) when reading data into the DataFrame (note that empty column identification may vary depending on the underlying engine being used).                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `raise_if_empty`      | `True`       | When there is no data in the sheet,`NoDataError` is raised. If this parameter is set to False, an empty DataFrame (with no columns) is returned instead.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

Excel's code reads the file with fsspec, then polars reads its bytes.

### Delta Lake (`delta`)

`DeltaLakeByPolarsOptions`: the arguments of
[`pl.scan_delta`](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_delta.html).

<!-- options: jupyter_storage_explorer_polars_support.DeltaLakeByPolarsOptions -->
| Option                | Default | Meaning                                                                                                                                                                           |
|-----------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `version`             | `None`  | Numerical version or timestamp version of the Delta lake table.<br>Note: If `version` is not provided, the latest version of delta lake table is read.                            |
| `delta_table_options` | `None`  | Additional keyword arguments while reading a Delta lake Table.                                                                                                                    |
| `use_pyarrow`         | `False` | Flag to enable pyarrow dataset reads.                                                                                                                                             |
| `pyarrow_options`     | `None`  | Keyword arguments while converting a Delta lake Table to pyarrow table. Use this parameter when filtering on partitioned columns or to read from a 'fsspec' supported filesystem. |
