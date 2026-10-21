# jupyter-storage-explorer-pyspark-support

PySpark support for Storage Explorer, the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
PySpark (or Databricks Connect) as an engine: the data browser on Spark DataFrames of Delta Lake tables, Parquet, CSV and JSON Lines, and code loading them.

```bash
pip install "jupyter-storage-explorer[pyspark]"          # the plugin and its libraries
pip install "jupyter-storage-explorer[pyspark-support]"  # the plugin only, with the libraries you have
```

Its libraries (`pyspark`, `delta-spark`) are not its dependencies, so that installing it never
changes those of a shared environment: the first command (or `jupyter-storage-explorer-pyspark-support[full]`) installs them too.
Explorers use every plugin installed, unless their `plugin_options` disable it: `{"pyspark-support": {"enabled": False}}`
(see [Plugins](https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#plugins)).

## Format options

The supports' options, in `format_options["pyspark"]` (by format, or `"*"` for all), configure the Spark session and
the reader, for the data browser and the code:

```python
StorageExplorer(
    "abfs://lake@myaccount.dfs.core.windows.net/raw",
    format_options={
        "pyspark": {
            "*": {
                "session_options": {
                    "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                    "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
                },
            },
            "csv": {"null_value": "NA", "mode": "DROPMALFORMED"},
            "delta": {"version_as_of": 3},
        },
    },
)
```

Every format takes:

| Option            | Default | Meaning                                                                                                                                                                       |
|-------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `session_options` | None    | Spark configuration, `SparkSession.builder.config(key, value)` for each. With a session already running in the kernel, only what Spark can change at run time applies.       |
| `reader_options`  | None    | `spark.read.option(key, value)` for each: options not listed below, e.g. Spark's [generic file source options](https://spark.apache.org/docs/latest/sql-data-sources-generic-options.html) (`{"recursiveFileLookup": True}`). They override the options below. |

The other options are the reader options of each format, in snake case (`null_value` is Spark's `nullValue`). Those
left unset (None) are left to Spark, whose defaults are shown. Options that look like credentials are left out of the
generated code.

### CSV (`csv`)

See Spark's [CSV data source options](https://spark.apache.org/docs/latest/sql-data-sources-csv.html#data-source-option).

| Option                              | Spark option                    | Default                                    | Meaning                                                                                         |
|-------------------------------------|---------------------------------|--------------------------------------------|-------------------------------------------------------------------------------------------------|
| `sep`                               | `sep`                           | detected                                   | The separator, one or more characters; by default, detected from the file's beginning.          |
| `encoding`                          | `encoding`                      | `UTF-8`                                    | The files' encoding.                                                                            |
| `quote`                             | `quote`                         | `"`                                        | The quote character; an empty string turns quotes off.                                          |
| `escape`                            | `escape`                        | `\`                                        | The character escaping quotes inside quoted values.                                             |
| `comment`                           | `comment`                       | (none)                                     | Lines beginning with this character are skipped.                                                |
| `header`                            | `header`                        | `True` (Spark's: `False`)                  | Whether the first line names the columns.                                                       |
| `infer_schema`                      | `inferSchema`                   | `True` (Spark's: `False`)                  | Whether the columns' types are inferred (an extra pass over the data); else all are strings.    |
| `prefer_date`                       | `preferDate`                    | `True`                                     | While inferring, string columns of dates become dates.                                          |
| `enforce_schema`                    | `enforceSchema`                 | `True`                                     | Whether the schema is applied without checking it against the files' headers.                   |
| `ignore_leading_white_space`        | `ignoreLeadingWhiteSpace`       | `False`                                    | Whether leading spaces of values are skipped.                                                   |
| `ignore_trailing_white_space`       | `ignoreTrailingWhiteSpace`      | `False`                                    | Whether trailing spaces of values are skipped.                                                  |
| `null_value`                        | `nullValue`                     | (none)                                     | The text of a null value.                                                                       |
| `nan_value`                         | `nanValue`                      | `NaN`                                      | The text of a non-number.                                                                       |
| `positive_inf`                      | `positiveInf`                   | `Inf`                                      | The text of positive infinity.                                                                  |
| `negative_inf`                      | `negativeInf`                   | `-Inf`                                     | The text of negative infinity.                                                                  |
| `date_format`                       | `dateFormat`                    | `yyyy-MM-dd`                               | Dates' format ([datetime patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-pattern.html)). |
| `timestamp_format`                  | `timestampFormat`               | `yyyy-MM-dd'T'HH:mm:ss[.SSS][XXX]`         | Timestamps' format.                                                                             |
| `timestamp_ntz_format`              | `timestampNTZFormat`            | `yyyy-MM-dd'T'HH:mm:ss[.SSS]`              | The format of timestamps without time zone.                                                     |
| `enable_date_time_parsing_fallback` | `enableDateTimeParsingFallback` | (by the parser policy and formats)         | Whether dates and timestamps not matching the formats are parsed as Spark 1.x and 2.0 did.       |
| `max_columns`                       | `maxColumns`                    | `20480`                                    | The most columns a record can have.                                                             |
| `max_chars_per_column`              | `maxCharsPerColumn`             | `-1`                                       | The most characters of a value; -1 for no limit.                                                |
| `mode`                              | `mode`                          | `PERMISSIVE`                               | Corrupt records: `PERMISSIVE` (nulls, the record in `column_name_of_corrupt_record`), `DROPMALFORMED` (dropped) or `FAILFAST` (an error). |
| `column_name_of_corrupt_record`     | `columnNameOfCorruptRecord`     | `spark.sql.columnNameOfCorruptRecord`      | The column of corrupt records in `PERMISSIVE` mode.                                             |
| `multi_line`                        | `multiLine`                     | `False`                                    | Whether quoted values may span lines.                                                           |
| `char_to_escape_quote_escaping`     | `charToEscapeQuoteEscaping`     | `escape`, or `\0`                          | The character escaping the quote's escape character.                                            |
| `sampling_ratio`                    | `samplingRatio`                 | `1.0`                                      | The fraction of rows read to infer the schema.                                                  |
| `empty_value`                       | `emptyValue`                    | (none)                                     | The text of an empty value.                                                                     |
| `locale`                            | `locale`                        | `en-US`                                    | The locale (IETF BCP 47) parsing dates and timestamps.                                          |
| `line_sep`                          | `lineSep`                       | `\r`, `\r\n` and `\n`                      | The line separator, one character.                                                              |
| `unescaped_quote_handling`          | `unescapedQuoteHandling`        | `STOP_AT_DELIMITER`                        | Values with unescaped quotes: `STOP_AT_CLOSING_QUOTE`, `BACK_TO_DELIMITER`, `STOP_AT_DELIMITER`, `SKIP_VALUE` or `RAISE_ERROR`. |
| `time_zone`                         | `timeZone`                      | `spark.sql.session.timeZone`               | The time zone of timestamps, e.g. `America/Los_Angeles` or `+01:00`.                            |

### JSON Lines (`json-lines`)

See Spark's [JSON data source options](https://spark.apache.org/docs/latest/sql-data-sources-json.html#data-source-option).

| Option                                   | Spark option                         | Default                               | Meaning                                                                               |
|------------------------------------------|--------------------------------------|---------------------------------------|---------------------------------------------------------------------------------------|
| `time_zone`                              | `timeZone`                           | `spark.sql.session.timeZone`          | The time zone of timestamps, e.g. `America/Los_Angeles` or `+01:00`.                  |
| `primitives_as_string`                   | `primitivesAsString`                 | `False`                               | Whether all primitive values are read as strings.                                     |
| `prefers_decimal`                        | `prefersDecimal`                     | `False`                               | Whether floating-point values are read as decimals (doubles if they do not fit).      |
| `allow_comments`                         | `allowComments`                      | `False`                               | Whether Java and C++ style comments are ignored.                                      |
| `allow_unquoted_field_names`             | `allowUnquotedFieldNames`            | `False`                               | Whether field names may be unquoted.                                                  |
| `allow_single_quotes`                    | `allowSingleQuotes`                  | `True`                                | Whether single quotes are allowed besides double quotes.                              |
| `allow_numeric_leading_zeros`            | `allowNumericLeadingZeros`           | `False`                               | Whether numbers may have leading zeros (e.g. 00012).                                  |
| `allow_backslash_escaping_any_character` | `allowBackslashEscapingAnyCharacter` | `False`                               | Whether a backslash may escape any character.                                         |
| `mode`                                   | `mode`                               | `PERMISSIVE`                          | Corrupt records: `PERMISSIVE` (nulls, the record in `column_name_of_corrupt_record`), `DROPMALFORMED` (dropped) or `FAILFAST` (an error). |
| `column_name_of_corrupt_record`          | `columnNameOfCorruptRecord`          | `spark.sql.columnNameOfCorruptRecord` | The column of corrupt records in `PERMISSIVE` mode.                                   |
| `date_format`                            | `dateFormat`                         | `yyyy-MM-dd`                          | Dates' format ([datetime patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-pattern.html)). |
| `timestamp_format`                       | `timestampFormat`                    | `yyyy-MM-dd'T'HH:mm:ss[.SSS][XXX]`    | Timestamps' format.                                                                   |
| `timestamp_ntz_format`                   | `timestampNTZFormat`                 | `yyyy-MM-dd'T'HH:mm:ss[.SSS]`         | The format of timestamps without time zone.                                           |
| `enable_date_time_parsing_fallback`      | `enableDateTimeParsingFallback`      | (by the parser policy and formats)    | Whether dates and timestamps not matching the formats are parsed as Spark 1.x and 2.0 did. |
| `multi_line`                             | `multiLine`                          | `False`                               | Whether each file is one record, which may span lines, instead of one per line.       |
| `allow_unquoted_control_chars`           | `allowUnquotedControlChars`          | `False`                               | Whether strings may contain unquoted control characters (e.g. tabs).                  |
| `encoding`                               | `encoding`                           | detected with `multi_line`            | The files' encoding, e.g. `UTF-16BE`.                                                 |
| `line_sep`                               | `lineSep`                            | `\r`, `\r\n` and `\n`                 | The line separator.                                                                   |
| `sampling_ratio`                         | `samplingRatio`                      | `1.0`                                 | The fraction of records read to infer the schema.                                     |
| `drop_field_if_all_null`                 | `dropFieldIfAllNull`                 | `False`                               | Whether columns of only nulls or empty arrays are dropped while inferring the schema. |
| `locale`                                 | `locale`                             | `en-US`                               | The locale (IETF BCP 47) parsing dates and timestamps.                                |
| `allow_non_numeric_numbers`              | `allowNonNumericNumbers`             | `True`                                | Whether `NaN`, `+INF` and `-INF` are numbers.                                         |
| `use_unsafe_row`                         | `useUnsafeRow`                       | `spark.sql.json.useUnsafeRow`         | Whether the parser represents structs as `UnsafeRow`.                                 |

### Parquet (`parquet`)

See Spark's [Parquet data source options](https://spark.apache.org/docs/latest/sql-data-sources-parquet.html#data-source-option).

| Option                 | Spark option         | Default                                       | Meaning                                                                                                   |
|------------------------|----------------------|-----------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `datetime_rebase_mode` | `datetimeRebaseMode` | `spark.sql.parquet.datetimeRebaseModeInRead`  | Ancient dates and timestamps, Julian to Proleptic Gregorian calendar: `EXCEPTION`, `CORRECTED` (as they are) or `LEGACY` (rebased). |
| `int96_rebase_mode`    | `int96RebaseMode`    | `spark.sql.parquet.int96RebaseModeInRead`     | The same for INT96 timestamps.                                                                            |
| `merge_schema`         | `mergeSchema`        | `spark.sql.parquet.mergeSchema`               | Whether the schemas of all the part files are merged.                                                     |

### Delta Lake (`delta`)

See Delta Lake's [DataFrameReader options](https://docs.delta.io/delta-batch/#dataframereader-options): an earlier
version of the table.

| Option            | Spark option    | Default | Meaning                                                                                       |
|-------------------|-----------------|---------|-----------------------------------------------------------------------------------------------|
| `timestamp_as_of` | `timestampAsOf` | (none)  | The table as of a date or a timestamp, e.g. `"2019-01-01"` or `"2019-01-01T00:00:00.000Z"`.   |
| `version_as_of`   | `versionAsOf`   | (none)  | The table's version of that number (`DESCRIBE HISTORY` lists them).                           |
