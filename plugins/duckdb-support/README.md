# jupyter-storage-explorer-duckdb-support

DuckDB support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
DuckDB as an engine: the data browser on Parquet, CSV, JSON Lines, Delta Lake tables and DuckDB databases, and code
loading them.

## Installation

```bash
pip install "jupyter-storage-explorer[duckdb]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[duckdb-support]"  # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them, as does `jupyter-storage-explorer-duckdb-support[full]`:

| Library   | Needed for                                                       |
|-----------|------------------------------------------------------------------|
| `duckdb`  | Mandatory: the engine                                            |
| `pyarrow` | Mandatory: the data browser collects DuckDB's results into it    |

Delta Lake tables need DuckDB's [delta extension](https://duckdb.org/docs/stable/core_extensions/delta), not a Python
package. DuckDB downloads it at the first query, unless its settings or your network forbid it. Install it beforehand
with `duckdb.install_extension("delta")` where the kernel cannot download it.

### Prerequisites

- DuckDB reads local files itself. On other storages, the plugin reads through the explorer's filesystem, with the
  explorer's credentials: DuckDB needs no configuration.
- DuckDB can also read cloud storage itself, with its
  [httpfs](https://duckdb.org/docs/stable/core_extensions/httpfs/overview) and
  [azure](https://duckdb.org/docs/stable/core_extensions/azure) extensions and their
  [secrets](https://duckdb.org/docs/stable/configuration/secrets_manager). Every view opens a connection of its own,
  so give the secrets as persistent secrets, which every connection loads.
- Once DuckDB reaches a storage, list its URL scheme in the `url_schemes` [engine option](#engine-options), e.g.
  `["s3"]`. The views then read it by URL.
- Delta Lake tables are read only by URL: on local disks and the storages of `url_schemes`. DuckDB cannot read them
  through the explorer's filesystem.

## How DuckDB reads your data

- Parquet files and folders are read lazily: DuckDB reads only the columns and row groups that each page, filter or
  sort needs.
  - Off the storages it reads itself, DuckDB reads through the explorer's filesystem.
  - DuckDB cannot read through filesystems without modification times, such as fsspec's HTTP and zip filesystems.
    There, it does not view Parquet.
- DuckDB reads a whole CSV or JSON Lines file again for each filter, sort or count. Off the storages it reads itself,
  the explorer first copies the file to the kernel's disk.
  - Files up to `max_whole_file_bytes`, 10 MB by default, are copied at once.
  - For larger files, you choose between copying the whole file and reading its first 10 MB into memory.
- DuckDB opens only local database files. The explorer copies other storages' databases to the kernel's disk first,
  and asks before copying one larger than `max_whole_file_bytes`.
- A copy is kept for 10 minutes after its last view closes, and while the remote file is unchanged. The copies are
  deleted when the kernel exits.
- A database shows its tables and views in a tree, by schema. The data browser opens the one you choose.
- "Python code" reads by URL the storages that DuckDB's extensions reach: local disks, S3, Google Cloud Storage,
  Azure, HTTP(S) and Hugging Face.
  - Elsewhere, such as on SFTP, the code registers fsspec's filesystem with DuckDB.
  - A remote database's code downloads it with fsspec, then opens it.

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    "s3://my-bucket/lake", plugin_options={"duckdb-support": {"priority": 10}}
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"duckdb-support": {"enabled": False}}
```

| Option     | Default | Meaning                                                                                                  |
|------------|---------|----------------------------------------------------------------------------------------------------------|
| `enabled`  | `True`  | Whether explorers use the plugin. `False`: not even imported.                                            |
| `priority` | lowest  | Plugins of a higher priority come first: their supports are tried before the others'. Equal ones by key. |

## Engine options

The supports' options, in `engine_options["duckdb"]` (by format, or `"*"` for all), for the data browser and the code:

```python
StorageExplorer(
    "s3://my-bucket/lake",
    engine_options={
        "duckdb": {
            "*": {"config": {"threads": 4}, "url_schemes": ["s3"]},
            "csv": {"na_values": ["NA"], "date_format": "%d/%m/%Y"},
            "delta": {"version": 3},
        },
    },
)
```

Every format takes:

| Option                   | Default | Meaning                                                                                                                                                                                         |
|--------------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `config`                 | `None`  | `duckdb.connect`'s `config`: DuckDB's [settings](https://duckdb.org/docs/stable/configuration/overview), e.g. `{"threads": 4, "memory_limit": "2GB"}`. Keys that look like credentials are left out of the code. |
| `url_schemes`            | `()`    | The URL schemes of the storages DuckDB reads itself, e.g. `["s3", "gs"]`. Local files are always read by URL. Other storages are read through the explorer's filesystem.                       |
| `fsspec_storage_options` | `None`  | fsspec's keyword arguments in the code on storages DuckDB's extensions do not reach, such as SFTP. Keys that look like credentials are left out.                                               |

The other options are each format's reader's arguments, of the same names, with their descriptions from DuckDB's
documentation. Those not set are not passed, so DuckDB's defaults, shown below, apply, except where the explorer sets
its own.

### Parquet (`parquet`)

`ParquetByDuckDBOptions`: the arguments of
[`read_parquet`](https://duckdb.org/docs/stable/data/parquet/overview#parameters).

| Option              | Default                        | Meaning                                                                                                                                                                       |
|---------------------|--------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `binary_as_string`  | `False`                        | Parquet files generated by legacy writers do not correctly set the UTF8 flag for strings, causing string columns to be loaded as BLOB instead. Set this to true to load binary columns as strings. |
| `file_row_number`   | `False`                        | Whether or not to include the `file_row_number` column.                                                                                                                       |
| `filename`          | `False`                        | Whether or not an extra `filename` column should be included in the result.                                                                                                   |
| `hive_partitioning` | the partition folders detected | Whether or not to interpret the path as a Hive partitioned path.                                                                                                              |
| `union_by_name`     | `False`                        | Whether the columns of multiple schemas should be unified by name, rather than by position.                                                                                   |

### CSV (`csv`)

`CsvByDuckDBOptions`: the arguments of [`read_csv`](https://duckdb.org/docs/stable/data/csv/overview#parameters).
DuckDB's sniffer detects the dialect, the header and the types of the options marked "detected".

| Option                 | Default              | Meaning                                                                                                                                                                  |
|------------------------|----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `header`               | detected             | Whether or not the CSV file has a header line.                                                                                                                           |
| `sep`                  | detected             | Delimiter character used to separate columns.                                                                                                                            |
| `quotechar`            | detected             | String used to quote a value.                                                                                                                                            |
| `escapechar`           | detected             | String used to escape characters within quoted values.                                                                                                                   |
| `comment`              | detected             | Character used to initiate comments. Lines starting with a comment character (optionally preceded by space characters) are completely ignored.                          |
| `lineterminator`       | detected             | The line terminator of the CSV file.                                                                                                                                     |
| `encoding`             | `'utf-8'`            | Encoding used by the CSV file: `utf-8`, `utf-16` or `latin-1`; others with the encodings extension.                                                                      |
| `compression`          | `'auto'`             | Method used to compress the CSV file. By default it is detected from the file extension, e.g. `t.csv.gz` uses gzip.                                                     |
| `skiprows`             | detected             | The number of lines at the top of the file to skip.                                                                                                                      |
| `names`                | `None`               | The column names, as a list.                                                                                                                                             |
| `columns`              | `None`               | The column names and types, as a dict, e.g. `{"a": "INTEGER"}`. It implies `auto_detect=False`.                                                                          |
| `dtype`                | `None`               | The column types, as a list (by position) or a dict (by name), e.g. `{"a": "DATE"}`.                                                                                     |
| `na_values`            | `''`                 | Strings that represent a NULL value.                                                                                                                                     |
| `force_not_null`       | `[]`                 | Do not match the specified columns' values against the NULL string. In the default case where the NULL string is empty, this means that empty values are read as zero-length strings rather than NULLs. |
| `allow_quoted_nulls`   | `True`               | Allow the conversion of quoted values to NULL values.                                                                                                                    |
| `all_varchar`          | `False`              | Skip type detection and assume all columns are of type VARCHAR.                                                                                                          |
| `auto_detect`          | `True`               | Auto detect CSV parameters.                                                                                                                                              |
| `auto_type_candidates` | DuckDB's list        | The types that the sniffer uses when detecting column types. The VARCHAR type is always included as a fallback option.                                                  |
| `sample_size`          | `20480`              | The number of sample rows for auto detection of parameters.                                                                                                              |
| `date_format`          | detected             | Date format used when parsing dates.                                                                                                                                     |
| `timestamp_format`     | detected             | Timestamp format used when parsing timestamps.                                                                                                                           |
| `decimal`              | `'.'`                | The decimal separator for numbers.                                                                                                                                       |
| `thousands`            | `None`               | Character used to identify thousands separators in numeric values. It must be a single character and different from the decimal separator.                              |
| `normalize_names`      | `False`              | Normalize column names: non-alphanumeric characters are removed, and reserved SQL keywords are prefixed with an underscore.                                             |
| `null_padding`         | `False`              | When a row lacks columns, pad the remaining columns on the right with NULL values.                                                                                      |
| `ignore_errors`        | `False`              | Ignore any parsing errors encountered.                                                                                                                                   |
| `strict_mode`          | `True`               | Enforces the strictness level of the CSV reader. When false, the reader tries to read structurally incorrect files, e.g. with unescaped quotes.                          |
| `max_line_size`        | `2000000`            | The maximum line size in bytes.                                                                                                                                          |
| `buffer_size`          | 16 × `max_line_size` | The buffer size in bytes for the CSV reader.                                                                                                                             |
| `parallel`             | `True`               | Whether or not the parallel CSV reader is used.                                                                                                                          |
| `store_rejects`        | `False`              | Skip any lines with errors and store them in the rejects table.                                                                                                          |
| `rejects_table`        | `'reject_errors'`    | Name of a temporary table where the information of faulty lines is stored.                                                                                               |
| `rejects_scan`         | `'reject_scans'`     | Name of a temporary table where the information of faulty scans is stored.                                                                                               |
| `rejects_limit`        | `0`                  | Upper limit on the number of faulty lines per file that are recorded in the rejects table. 0 means no limit.                                                            |
| `filename`             | `False`              | Whether or not an extra `filename` column should be included in the result.                                                                                              |

### JSON Lines (`json-lines`)

`JsonLinesByDuckDBOptions`: the arguments of [`read_json`](https://duckdb.org/docs/stable/data/json/loading_json#parameters).

| Option                        | Default                                       | Meaning                                                                                                                                                                                       |
|-------------------------------|-----------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `columns`                     | detected                                      | The key names and value types in the JSON file, as a dict, e.g. `{"key1": "INTEGER", "key2": "VARCHAR"}`.                                                                                     |
| `format`                      | `'auto'`; the explorer: `'newline_delimited'` | One of `'auto'`, `'unstructured'`, `'newline_delimited'` and `'array'`.                                                                                                                       |
| `records`                     | `'auto'`                                      | One of `'auto'`, `'true'` and `'false'`: whether the JSON contains records whose keys become columns.                                                                                        |
| `sample_size`                 | `20480`                                       | The number of sample objects for the automatic detection of types. Set it to -1 to scan the entire input file.                                                                              |
| `maximum_depth`               | `-1`                                          | The maximum nesting depth to which the automatic schema detection detects types. Set it to -1 to fully detect nested JSON types.                                                             |
| `maximum_object_size`         | `16777216`                                    | The size of the largest JSON object, in bytes.                                                                                                                                                |
| `date_format`                 | `'iso'`                                       | The date format to use when parsing dates.                                                                                                                                                    |
| `timestamp_format`            | `'iso'`                                       | The timestamp format to use when parsing timestamps.                                                                                                                                          |
| `compression`                 | `'auto'`                                      | The compression type of the file. By default it is detected from the file extension.                                                                                                          |
| `ignore_errors`               | `False`                                       | Whether to ignore parse errors: only possible for newline-delimited JSON.                                                                                                                    |
| `convert_strings_to_integers` | `False`                                       | Whether strings representing integer values should be converted to a numerical type.                                                                                                          |
| `field_appearance_threshold`  | `0.1`                                         | The reader divides the number of appearances of each field by the sample size. If the average over the fields of an object is below this threshold, the object becomes a MAP. |
| `map_inference_threshold`     | `200`                                         | An object of more fields than this threshold becomes a MAP, rather than a STRUCT. Set it to -1 to disable the inference of MAPs.                                                            |
| `filename`                    | `False`                                       | Whether or not an extra `filename` column should be included in the result.                                                                                                                   |

### Delta Lake (`delta`)

`DeltaLakeByDuckDBOptions`: the named parameters of the delta extension's
[`delta_scan`](https://duckdb.org/docs/stable/core_extensions/delta).

| Option             | Default  | Meaning                                                                    |
|--------------------|----------|----------------------------------------------------------------------------|
| `version`          | latest   | The version of the table to read.                                          |
| `binary_as_string` | `False`  | Load binary columns as strings, as for Parquet.                            |
| `file_row_number`  | `False`  | Whether or not to include the `file_row_number` column.                    |
| `filename`         | `False`  | Whether or not an extra `filename` column should be included in the result. |

### DuckDB databases (`duckdb`)

`DuckDBOptions`: the options every format takes. The database is opened read only, with `config`.
