"""Formats handled with Spark (PySpark), as actions: the data browser, on a
Spark DataFrame (lazy: each page a Spark job), and load code. Spark reads
with its own storage configuration (``PySparkOptions.session_options``), and
reads the item's URL, rewritten as Spark reads it (``spark_url``): the
explorer's filesystem is not used, and storages Spark cannot reach (e.g.
fsspec's memory filesystem) cannot be viewed.

Each format has a view and its code, registered in order in
``PYSPARK_ACTIONS``. pyspark is imported inside the functions, so that the
plugin loads without it."""

from __future__ import annotations

import time
from dataclasses import dataclass, fields
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

import narwhals as nw

from jupyter_storage_explorer.actions import (
    ActionOptions,
    code,
    get_logger,
    register_actions,
    view,
)
from jupyter_storage_explorer.base import ItemContext
from jupyter_storage_explorer.engine import Engine
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.packages import PyArrow, PythonPackage
from jupyter_storage_explorer.util import format_kwargs, option_field
from jupyter_storage_explorer.views import QueryView, View, ViewLimits

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from dataclasses import Field

    from jupyter_storage_explorer.formats.base import DataFormat

log = get_logger(__name__)

# Spark (Hadoop) names for storage URLs: TLS "abfss" for Azure, as Spark
# expects it (storage accounts usually require secure transfer); "s3a", the
# S3 connector of open-source Hadoop (Databricks and EMR accept it too).
_SPARK_SCHEMES = {"abfs": "abfss", "az": "abfss", "s3": "s3a"}


# The engine's libraries, and those only Spark uses (the support libraries
# several engines use are the core's: jupyter_storage_explorer.packages).


class PySpark(PythonPackage):
    """pyspark, with which sessions are made by ``SparkSession.builder``."""

    package = "pyspark"
    import_name = "pyspark"
    # A package may bring a pyspark module of its own, under its own
    # distribution, e.g. Databricks Connect, whose builder makes no local
    # session: the module counts only with pyspark's own distribution.
    own_distribution = True


class DeltaSpark(PythonPackage):
    """Delta Lake for Spark, set up in the session (on Databricks, it is)."""

    package = "delta-spark"
    import_name = "delta"


def spark_url(url: str) -> str:
    """``url`` as Spark reads it, e.g. "abfss://c@a.dfs.core.windows.net/x" for
    "abfs://c@a.dfs.core.windows.net/x" or "s3a://bucket/x" for "s3://bucket/x";
    Databricks' "dbfs:/Volumes/x" for "dbfs://Volumes/x" (fsspec's form, see
    ``DatabricksMapper``), whose "Volumes" Spark would take for a host.

    Other URLs and local paths are unchanged.
    """
    scheme, sep, rest = url.partition("://")
    if sep and scheme == "dbfs":
        return f"dbfs:/{rest.lstrip('/')}"
    return (
        f"{_SPARK_SCHEMES[scheme]}://{rest}"
        if sep and scheme in _SPARK_SCHEMES
        else url
    )


def spark_session(session_options: Mapping[str, Any] | None = None) -> Any:
    """The Spark session views read with: the active one (e.g. the
    notebook's on Databricks, or one the user created in the kernel), else
    one created by pyspark.

    ``session_options`` are given to the session's builder (``config(key,
    value)``); with a session already running, ``getOrCreate`` returns it,
    applying those Spark can still change (runtime configuration)."""
    from pyspark.sql import SparkSession

    active = SparkSession.getActiveSession()
    if active is not None and not session_options:
        log.debug("The active Spark session used")
        return active
    builder = SparkSession.builder
    for key, value in (session_options or {}).items():
        builder = builder.config(key, value)
    # Before as well as after: a session starting can take minutes, or hang.
    log.debug(
        "Calling SparkSession.builder.getOrCreate(), with %d session options",
        len(session_options or {}),
    )
    started = time.monotonic()
    session = builder.getOrCreate()
    # Their count only: their values may be credentials, e.g. an account key.
    log.info(
        "Spark session %s in %.1f s, with %d session options",
        "found" if active is not None else "ready",
        time.monotonic() - started,
        len(session_options or {}),
    )
    return session


def _url(ctx: ItemContext) -> str:
    return spark_url(ctx.location.url)


def spark_rows(lf: Any, offset: int, length: int) -> Any:
    """Rows ``offset`` to ``offset + length`` of a Spark query, for the data
    browser (``QueryView.fetch``): skipped by Spark itself with
    ``DataFrame.offset`` (Spark 3.4 and later, Spark Connect too), rather
    than all rows up to ``offset + length`` read and the first dropped, the
    explorer's default. None, so the default reads them, with a Spark
    without it.

    Pages are separate Spark jobs: they line up only if Spark gives the
    result in the same order each time, e.g. sorted by columns telling all
    rows apart.

    Parameters
    ----------
    lf : narwhals.LazyFrame
        The query, on a Spark DataFrame.
    offset, length : int
        The first row, and the most rows.

    Returns
    -------
    narwhals.DataFrame or None
    """
    native = lf.to_native()
    # On the class: a DataFrame's attributes are also its columns.
    if offset and not callable(getattr(type(native), "offset", None)):
        return None
    page = (native.offset(offset) if offset else native).limit(length)
    return nw.from_native(page).collect()


class PySparkEngine(Engine):
    """Spark's Python API, with pyspark."""

    key = "pyspark"
    label = "PySpark"
    # PyArrow: the data browser reads Spark's rows into it, through narwhals.
    requirements = (PySpark(), PyArrow())


# The URL schemes Spark reads by default, as Spark names them (``spark_url``):
# local files, HDFS, S3 (s3a), Google Cloud Storage, Azure (ABFS, WASB) and
# Databricks (dbfs). Each needs its connector in the session, as configured.
SPARK_PROTOCOLS = (
    "file",
    "hdfs",
    "s3a",
    "gs",
    "abfss",
    "abfs",
    "wasbs",
    "wasb",
    "dbfs",
)
# Field metadata: the reader option's name in Spark, when it is not the
# field's name in camel case (e.g. "timestampNTZFormat").
SPARK_NAME = "spark_name"


def _spark_name(field: Field[Any]) -> str:
    """The reader option a field of the options sets: ``infer_schema`` is
    ``inferSchema``."""
    first, *rest = field.name.split("_")
    return field.metadata.get(SPARK_NAME, first + "".join(w.title() for w in rest))


def _merged(*options: Mapping[str, Any]) -> dict[str, Any]:
    """``options`` merged, later ones winning. Spark's option names ignore
    case, so a later key replaces an earlier one in another case."""
    by_lower: dict[str, tuple[str, Any]] = {}
    for given in options:
        for key, value in given.items():
            by_lower[key.lower()] = (key, value)
    return dict(by_lower.values())


@dataclass(frozen=True, kw_only=True)
class PySparkOptions(ActionOptions):
    """The options of the formats Spark reads, for the data browser and the
    code. Each format's subclass adds its reader options as fields
    (``CsvByPySparkOptions``, ...): None, their default, leaves the option to
    Spark.
    """

    session_options: Mapping[str, Any] | None = option_field(
        (
            "Spark configuration, `SparkSession.builder.config(key, value)` for"
            " each. With a session already running in the kernel, only what "
            "Spark can change at run time applies."
        ),
        default=None,
    )
    reader_options: Mapping[str, Any] | None = option_field(
        (
            "`spark.read.option(key, value)` for each: options not listed "
            "below, e.g. Spark's [generic file source "
            "options](https://spark.apache.org/docs/latest/sql-data-sources-"
            'generic-options.html) (`{"recursiveFileLookup": True}`). They '
            "override the options below."
        ),
        default=None,
    )
    supported_protocols: Sequence[str] | None = option_field(
        (
            "The URL schemes Spark reads, as Spark names them: by default "
            "`file`, `hdfs`, `s3a`, `gs`, `abfss`, `abfs`, `wasbs`, `wasb` and "
            "`dbfs`. Items elsewhere, e.g. on SFTP, are neither viewed nor "
            "given code with Spark. `None`: any."
        ),
        default=SPARK_PROTOCOLS,
        shown_default="`SPARK_PROTOCOLS`",
    )

    def format_options(self, *, in_code: bool = False) -> dict[str, Any]:
        """The format's reader options the fields set, by Spark's names: the
        fields of each format's subclass, those not None.

        Parameters
        ----------
        in_code : bool, default False
            Only those fit to show in code (``code_value``).

        Returns
        -------
        dict
            E.g. ``{"header": True, "inferSchema": True}``.
        """
        own = {f.name for f in fields(PySparkOptions)}
        return {
            _spark_name(f): value
            for f in fields(self)
            if f.name not in own
            and (value := self.code_value(f.name) if in_code else getattr(self, f.name))
            is not None
        }


# What the actions do with the options: functions of them, so that the
# options stay data.


def spark_reader(
    options: PySparkOptions, spark: Any, defaults: Mapping[str, Any] | None = None
) -> Any:
    """``spark.read`` with the reader options.

    Parameters
    ----------
    options : PySparkOptions
        A format's options.
    spark : SparkSession
        The session to read with.
    defaults : mapping, optional
        Reader options the action sets, e.g. CSV's separator detected.

    Returns
    -------
    DataFrameReader
        ``spark.read`` with ``defaults``, then the fields' options, then
        ``reader_options``, each overriding the previous ones.
    """
    reader = spark.read
    settings = _merged(
        defaults or {}, options.format_options(), options.reader_options or {}
    )
    for key, value in settings.items():
        reader = reader.option(key, value)
    return reader


def spark_session_code(options: PySparkOptions) -> str:
    """The code's lines creating the session with pyspark's builder, with
    ``session_options`` (those fit to show).

    Parameters
    ----------
    options : PySparkOptions
        A format's options.

    Returns
    -------
    str
        E.g. ``"spark = SparkSession.builder.getOrCreate()"``.
    """
    config = options.code_value("session_options") or {}
    if not config:
        return "spark = SparkSession.builder.getOrCreate()"
    lines = [f"    .config({key!r}, {value!r})" for key, value in config.items()]
    return "\n".join(
        ["spark = (", "    SparkSession.builder", *lines, "    .getOrCreate()", ")"]
    )


def spark_reader_code(
    options: PySparkOptions, defaults: Mapping[str, Any] | None = None
) -> str:
    """What follows ``spark.read`` in the code.

    Parameters
    ----------
    options : PySparkOptions
        A format's options.
    defaults : mapping, optional
        Reader options the action sets, e.g. CSV's separator detected.

    Returns
    -------
    str
        ``.options(...)`` with ``defaults`` and the fields' options but those
        ``reader_options`` override, then an ``.option(key, value)`` per
        reader option; only those fit to show.
    """
    overridden = {key.lower() for key in options.reader_options or {}}
    shown = options.format_options(in_code=True)
    settings = {
        key: value
        for key, value in _merged(defaults or {}, shown).items()
        if value is not None and key.lower() not in overridden
    }
    arguments = format_kwargs(**settings).removeprefix(", ")
    reader = options.code_value("reader_options") or {}
    return (f".options({arguments})" if arguments else "") + "".join(
        f".option({key!r}, {value!r})" for key, value in reader.items()
    )


# The formats' reader options, from Spark's documentation of its data sources
# (https://spark.apache.org/docs/latest/sql-data-sources.html, "Data Source
# Option", those read; generic file source options go in reader_options) and
# Delta Lake's (https://docs.delta.io/delta-batch/, time travel). Each field
# is the option of its name in camel case unless SPARK_NAME says otherwise.
# The plugin's README shows their descriptions, by docs/scripts/option_tables.py.


@dataclass(frozen=True, kw_only=True)
class CsvByPySparkOptions(PySparkOptions):
    """Spark's CSV reader options (``spark.read.csv``), besides the session's
    and ``reader_options``.

    Each field is the option of its name in camel case (``null_value`` is
    ``nullValue``; ``timestamp_ntz_format``, ``timestampNTZFormat``),
    documented in Spark's "CSV Files"; None leaves it to Spark. The plugin's
    README lists them.
    """

    sep: str | None = option_field(
        (
            "Sets a separator for each field and value. This separator can be "
            "one or more characters. By default, the one detected from the "
            "file's beginning."
        ),
        default=None,
        shown_default="detected",
    )
    encoding: str | None = option_field(
        "Decodes the CSV files by the given encoding type.",
        default=None,
        shown_default="`UTF-8`",
    )
    quote: str | None = option_field(
        (
            "Sets a single character used for escaping quoted values where the "
            "separator can be part of the value. To turn off quotations, set "
            "not None but an empty string."
        ),
        default=None,
        shown_default='`"`',
    )
    escape: str | None = option_field(
        (
            "Sets a single character used for escaping quotes inside an already"
            " quoted value."
        ),
        default=None,
        shown_default="`\\`",
    )
    comment: str | None = option_field(
        (
            "Sets a single character used for skipping lines beginning with "
            "this character. By default, it is disabled."
        ),
        default=None,
        shown_default="(none)",
    )
    header: bool | None = option_field(
        "Uses the first line as names of columns.", default=True
    )
    infer_schema: bool | None = option_field(
        (
            "Infers the input schema automatically from data. It requires one "
            "extra pass over the data."
        ),
        default=True,
    )
    prefer_date: bool | None = option_field(
        (
            "During schema inference (`infer_schema`), attempts to infer string"
            " columns that contain dates as `Date` if the values satisfy the "
            "`date_format` option or default date format. For columns that "
            "contain a mixture of dates and timestamps, try inferring them as "
            "`TimestampType` if timestamp format not specified, otherwise infer"
            " them as `StringType`."
        ),
        default=None,
        shown_default="`True`",
    )
    enforce_schema: bool | None = option_field(
        (
            "If `True`, the specified or inferred schema will be forcibly "
            "applied to datasource files, and headers in CSV files will be "
            "ignored. If `False`, the schema will be validated against all "
            "headers in CSV files when `header` is `True`. Field names in the "
            "schema and column names in CSV headers are checked by their "
            "positions taking into account `spark.sql.caseSensitive`."
        ),
        default=None,
        shown_default="`True`",
    )
    ignore_leading_white_space: bool | None = option_field(
        (
            "Whether or not leading whitespaces from values being read should "
            "be skipped."
        ),
        default=None,
        shown_default="`False`",
    )
    ignore_trailing_white_space: bool | None = option_field(
        (
            "Whether or not trailing whitespaces from values being read should "
            "be skipped."
        ),
        default=None,
        shown_default="`False`",
    )
    null_value: str | None = option_field(
        (
            "Sets the string representation of a null value. It applies to all "
            "supported types including the string type."
        ),
        default=None,
        shown_default="(none)",
    )
    nan_value: str | None = option_field(
        "Sets the string representation of a non-number value.",
        default=None,
        shown_default="`NaN`",
    )
    positive_inf: str | None = option_field(
        "Sets the string representation of a positive infinity value.",
        default=None,
        shown_default="`Inf`",
    )
    negative_inf: str | None = option_field(
        "Sets the string representation of a negative infinity value.",
        default=None,
        shown_default="`-Inf`",
    )
    date_format: str | None = option_field(
        (
            "Sets the string that indicates a date format. Custom date formats "
            "follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to date type."
        ),
        default=None,
        shown_default="`yyyy-MM-dd`",
    )
    timestamp_format: str | None = option_field(
        (
            "Sets the string that indicates a timestamp format. Custom date "
            "formats follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to timestamp type."
        ),
        default=None,
        shown_default="`yyyy-MM-dd'T'HH:mm:ss[.SSS][XXX]`",
    )
    timestamp_ntz_format: str | None = option_field(
        (
            "Sets the string that indicates a timestamp without timezone "
            "format. Custom date formats follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to timestamp without timezone type; "
            "zone-offset and time-zone components are not supported when "
            "reading this data type."
        ),
        default=None,
        metadata={SPARK_NAME: "timestampNTZFormat"},
        shown_default="`yyyy-MM-dd'T'HH:mm:ss[.SSS]`",
    )
    enable_date_time_parsing_fallback: bool | None = option_field(
        (
            "Allows falling back to the backward compatible (Spark 1.x and 2.0)"
            " behavior of parsing dates and timestamps if values do not match "
            "the set patterns."
        ),
        default=None,
        shown_default=(
            "Enabled if the time parser policy has legacy settings or if no "
            "custom date or timestamp pattern was provided"
        ),
    )
    max_columns: int | None = option_field(
        "Defines a hard limit of how many columns a record can have.",
        default=None,
        shown_default="`20480`",
    )
    max_chars_per_column: int | None = option_field(
        (
            "Defines the maximum number of characters allowed for any given "
            "value being read. By default, it is -1 meaning unlimited length."
        ),
        default=None,
        shown_default="`-1`",
    )
    mode: str | None = option_field(
        (
            "Allows a mode for dealing with corrupt records during parsing "
            "(case-insensitive). Spark tries to parse only required columns in "
            "CSV under column pruning, so corrupt records can be different "
            "based on required set of fields "
            "(`spark.sql.csv.parser.columnPruning.enabled`, enabled by "
            "default).\n• `PERMISSIVE`: when it meets a corrupted record, "
            "puts the malformed string into a field configured by "
            "`column_name_of_corrupt_record`, and sets malformed fields to "
            "null. To keep corrupt records, set a string type field named "
            "`column_name_of_corrupt_record` in a user-defined schema; if a "
            "schema does not have the field, it drops corrupt records during "
            "parsing. A record with less or more tokens than the schema is not "
            "a corrupted record: fewer tokens set nulls to the extra fields, "
            "more tokens are dropped.\n• `DROPMALFORMED`: ignores the whole "
            "corrupted records.\n• `FAILFAST`: throws an exception when it "
            "meets corrupted records."
        ),
        default=None,
        shown_default="`PERMISSIVE`",
    )
    column_name_of_corrupt_record: str | None = option_field(
        (
            "Allows renaming the new field having malformed string created by "
            "`PERMISSIVE` mode. This overrides "
            "`spark.sql.columnNameOfCorruptRecord`."
        ),
        default=None,
        shown_default="the value of `spark.sql.columnNameOfCorruptRecord`",
    )
    multi_line: bool | None = option_field(
        (
            "Allows a row to span multiple lines, by parsing line breaks within"
            " quoted values as part of the value itself."
        ),
        default=None,
        shown_default="`False`",
    )
    char_to_escape_quote_escaping: str | None = option_field(
        (
            "Sets a single character used for escaping the escape for the quote"
            " character. The default value is the escape character when escape "
            "and quote characters are different, `\\0` otherwise."
        ),
        default=None,
        shown_default="`escape` or `\\0`",
    )
    sampling_ratio: float | None = option_field(
        "Defines fraction of rows used for schema inferring.",
        default=None,
        shown_default="`1.0`",
    )
    empty_value: str | None = option_field(
        "Sets the string representation of an empty value.",
        default=None,
        shown_default="(none)",
    )
    locale: str | None = option_field(
        (
            "Sets a locale as language tag in IETF BCP 47 format. For instance,"
            " this is used while parsing dates and timestamps."
        ),
        default=None,
        shown_default="`en-US`",
    )
    line_sep: str | None = option_field(
        (
            "Defines the line separator that should be used for parsing. "
            "Maximum length is 1 character."
        ),
        default=None,
        shown_default="`\\r`, `\\r\\n` and `\\n`",
    )
    unescaped_quote_handling: str | None = option_field(
        (
            "Defines how the CSV parser will handle values with unescaped "
            "quotes.\n• `STOP_AT_CLOSING_QUOTE`: if unescaped quotes are "
            "found in the input, accumulate the quote character and proceed "
            "parsing the value as a quoted value, until a closing quote is "
            "found.\n• `BACK_TO_DELIMITER`: if unescaped quotes are found in "
            "the input, consider the value as an unquoted value. The parser "
            "accumulates all characters of the current parsed value until the "
            "delimiter is found. If no delimiter is found in the value, it "
            "continues accumulating characters from the input until a delimiter"
            " or line ending is found.\n• `STOP_AT_DELIMITER`: if unescaped "
            "quotes are found in the input, consider the value as an unquoted "
            "value. The parser accumulates all characters until the delimiter "
            "or a line ending is found in the input.\n• `SKIP_VALUE`: if "
            "unescaped quotes are found in the input, the content parsed for "
            "the given value will be skipped and the value set in `null_value` "
            "will be produced instead.\n• `RAISE_ERROR`: if unescaped quotes "
            "are found in the input, a `TextParsingException` will be thrown."
        ),
        default=None,
        shown_default="`STOP_AT_DELIMITER`",
    )
    time_zone: str | None = option_field(
        (
            "Sets the string that indicates a time zone ID to be used to format"
            " timestamps or partition values.\n• Region-based zone ID: it "
            "should have the form 'area/city', such as "
            "'America/Los_Angeles'.\n• Zone offset: it should be in the "
            "format '(+|-)HH:mm', for example '-08:00' or '+01:00'. Also 'UTC'"
            " and 'Z' are supported as aliases of '+00:00'.\nOther short "
            "names like 'CST' are not recommended to use because they can be "
            "ambiguous."
        ),
        default=None,
        shown_default="the value of `spark.sql.session.timeZone`",
    )


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPySparkOptions(PySparkOptions):
    """Spark's JSON reader options (``spark.read.json``), besides the
    session's and ``reader_options``.

    Each field is the option of its name in camel case
    (``primitives_as_string`` is ``primitivesAsString``;
    ``timestamp_ntz_format``, ``timestampNTZFormat``), documented in Spark's
    "JSON Files"; None leaves it to Spark. The plugin's README lists them.
    """

    time_zone: str | None = option_field(
        (
            "Sets the string that indicates a time zone ID to be used to format"
            " timestamps or partition values.\n• Region-based zone ID: it "
            "should have the form 'area/city', such as "
            "'America/Los_Angeles'.\n• Zone offset: it should be in the "
            "format '(+|-)HH:mm', for example '-08:00' or '+01:00'. Also 'UTC'"
            " and 'Z' are supported as aliases of '+00:00'.\nOther short "
            "names like 'CST' are not recommended to use because they can be "
            "ambiguous."
        ),
        default=None,
        shown_default="the value of `spark.sql.session.timeZone`",
    )
    primitives_as_string: bool | None = option_field(
        "Infers all primitive values as a string type.",
        default=None,
        shown_default="`False`",
    )
    prefers_decimal: bool | None = option_field(
        (
            "Infers all floating-point values as a decimal type. If the values "
            "do not fit in decimal, then it infers them as doubles."
        ),
        default=None,
        shown_default="`False`",
    )
    allow_comments: bool | None = option_field(
        "Ignores Java/C++ style comment in JSON records.",
        default=None,
        shown_default="`False`",
    )
    allow_unquoted_field_names: bool | None = option_field(
        "Allows unquoted JSON field names.", default=None, shown_default="`False`"
    )
    allow_single_quotes: bool | None = option_field(
        "Allows single quotes in addition to double quotes.",
        default=None,
        shown_default="`True`",
    )
    allow_numeric_leading_zeros: bool | None = option_field(
        "Allows leading zeros in numbers (e.g. 00012).",
        default=None,
        shown_default="`False`",
    )
    allow_backslash_escaping_any_character: bool | None = option_field(
        (
            "Allows accepting quoting of all character using backslash quoting "
            "mechanism."
        ),
        default=None,
        shown_default="`False`",
    )
    mode: str | None = option_field(
        (
            "Allows a mode for dealing with corrupt records during "
            "parsing.\n• `PERMISSIVE`: when it meets a corrupted record, puts"
            " the malformed string into a field configured by "
            "`column_name_of_corrupt_record`, and sets malformed fields to "
            "null. To keep corrupt records, set a string type field named "
            "`column_name_of_corrupt_record` in a user-defined schema; if a "
            "schema does not have the field, it drops corrupt records during "
            "parsing. When inferring a schema, it implicitly adds a "
            "`column_name_of_corrupt_record` field in an output schema.\n• "
            "`DROPMALFORMED`: ignores the whole corrupted records.\n• "
            "`FAILFAST`: throws an exception when it meets corrupted records."
        ),
        default=None,
        shown_default="`PERMISSIVE`",
    )
    column_name_of_corrupt_record: str | None = option_field(
        (
            "Allows renaming the new field having malformed string created by "
            "`PERMISSIVE` mode. This overrides "
            "`spark.sql.columnNameOfCorruptRecord`."
        ),
        default=None,
        shown_default="the value of `spark.sql.columnNameOfCorruptRecord`",
    )
    date_format: str | None = option_field(
        (
            "Sets the string that indicates a date format. Custom date formats "
            "follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to date type."
        ),
        default=None,
        shown_default="`yyyy-MM-dd`",
    )
    timestamp_format: str | None = option_field(
        (
            "Sets the string that indicates a timestamp format. Custom date "
            "formats follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to timestamp type."
        ),
        default=None,
        shown_default="`yyyy-MM-dd'T'HH:mm:ss[.SSS][XXX]`",
    )
    timestamp_ntz_format: str | None = option_field(
        (
            "Sets the string that indicates a timestamp without timezone "
            "format. Custom date formats follow the formats at [Datetime "
            "Patterns](https://spark.apache.org/docs/latest/sql-ref-datetime-"
            "pattern.html). This applies to timestamp without timezone type; "
            "zone-offset and time-zone components are not supported when "
            "reading this data type."
        ),
        default=None,
        metadata={SPARK_NAME: "timestampNTZFormat"},
        shown_default="`yyyy-MM-dd'T'HH:mm:ss[.SSS]`",
    )
    enable_date_time_parsing_fallback: bool | None = option_field(
        (
            "Allows falling back to the backward compatible (Spark 1.x and 2.0)"
            " behavior of parsing dates and timestamps if values do not match "
            "the set patterns."
        ),
        default=None,
        shown_default=(
            "Enabled if the time parser policy has legacy settings or if no "
            "custom date or timestamp pattern was provided"
        ),
    )
    multi_line: bool | None = option_field(
        "Parse one record, which may span multiple lines, per file.",
        default=None,
        shown_default="`False`",
    )
    allow_unquoted_control_chars: bool | None = option_field(
        (
            "Allows JSON Strings to contain unquoted control characters (ASCII "
            "characters with value less than 32, including tab and line feed "
            "characters) or not."
        ),
        default=None,
        shown_default="`False`",
    )
    encoding: str | None = option_field(
        (
            "Allows to forcibly set one of standard basic or extended encoding "
            "for the JSON files. For example UTF-16BE, UTF-32LE."
        ),
        default=None,
        shown_default="detected automatically when `multi_line` is `True`",
    )
    line_sep: str | None = option_field(
        "Defines the line separator that should be used for parsing.",
        default=None,
        shown_default="`\\r`, `\\r\\n` and `\\n`",
    )
    sampling_ratio: float | None = option_field(
        "Defines fraction of input JSON objects used for schema inferring.",
        default=None,
        shown_default="`1.0`",
    )
    drop_field_if_all_null: bool | None = option_field(
        (
            "Whether to ignore column of all null values or empty array during "
            "schema inference."
        ),
        default=None,
        shown_default="`False`",
    )
    locale: str | None = option_field(
        (
            "Sets a locale as language tag in IETF BCP 47 format. For instance,"
            " it is used while parsing dates and timestamps."
        ),
        default=None,
        shown_default="`en-US`",
    )
    allow_non_numeric_numbers: bool | None = option_field(
        (
            'Allows JSON parser to recognize set of "Not-a-Number" (NaN) tokens'
            " as legal floating number values.\n• `+INF`: for positive "
            "infinity, as well as alias of `+Infinity` and `Infinity`.\n• "
            "`-INF`: for negative infinity, alias `-Infinity`.\n• `NaN`: for "
            "other not-a-numbers, like result of division by zero."
        ),
        default=None,
        shown_default="`True`",
    )
    use_unsafe_row: bool | None = option_field(
        ("Whether to use UnsafeRow to represent struct result in the JSON parser."),
        default=None,
        shown_default="the value of `spark.sql.json.useUnsafeRow`",
    )


@dataclass(frozen=True, kw_only=True)
class ParquetByPySparkOptions(PySparkOptions):
    """Spark's Parquet reader options (``spark.read.parquet``), besides the
    session's and ``reader_options``.

    Each field is the option of its name in camel case (``merge_schema`` is
    ``mergeSchema``), documented in Spark's "Parquet Files"; None leaves it
    to Spark (its session's configuration). The plugin's README lists them.
    """

    datetime_rebase_mode: str | None = option_field(
        (
            "Specifies the rebasing mode for the values of the `DATE`, "
            "`TIMESTAMP_MILLIS`, `TIMESTAMP_MICROS` logical types from the "
            "Julian to Proleptic Gregorian calendar.\n• `EXCEPTION`: fails in"
            " reads of ancient dates/timestamps that are ambiguous between the "
            "two calendars.\n• `CORRECTED`: loads dates/timestamps without "
            "rebasing.\n• `LEGACY`: performs rebasing of ancient "
            "dates/timestamps from the Julian to Proleptic Gregorian calendar."
        ),
        default=None,
        shown_default="the value of `spark.sql.parquet.datetimeRebaseModeInRead`",
    )
    int96_rebase_mode: str | None = option_field(
        (
            "Specifies the rebasing mode for INT96 timestamps from the Julian "
            "to Proleptic Gregorian calendar.\n• `EXCEPTION`: fails in reads "
            "of ancient INT96 timestamps that are ambiguous between the two "
            "calendars.\n• `CORRECTED`: loads INT96 timestamps without "
            "rebasing.\n• `LEGACY`: performs rebasing of ancient timestamps "
            "from the Julian to Proleptic Gregorian calendar."
        ),
        default=None,
        shown_default="the value of `spark.sql.parquet.int96RebaseModeInRead`",
    )
    merge_schema: bool | None = option_field(
        (
            "Sets whether we should merge schemas collected from all Parquet "
            "part-files. This overrides `spark.sql.parquet.mergeSchema`."
        ),
        default=None,
        shown_default="the value of `spark.sql.parquet.mergeSchema`",
    )


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByPySparkOptions(PySparkOptions):
    """Delta Lake's reader options for time travel, besides the session's and
    ``reader_options``: a table's earlier version.
    """

    timestamp_as_of: str | None = option_field(
        (
            "Loads the table as it was at a point in time. Only date or "
            'timestamp strings are accepted, e.g. `"2019-01-01"` or '
            '`"2019-01-01T00:00:00.000Z"`.'
        ),
        default=None,
        shown_default="(none)",
    )
    version_as_of: int | None = option_field(
        (
            "Loads the table at a version, a number; `DESCRIBE HISTORY` on the "
            "table lists them."
        ),
        default=None,
        shown_default="(none)",
    )


# How the actions make Spark sessions: pyspark-support's with pyspark's
# SparkSession.builder (``PYSPARK_SESSIONS``). Another engine making them
# another way, e.g. databricks-support's with Databricks Connect, defines its
# own actions with the same helpers (``spark_csv_view``, ...) and its sessions.


@dataclass(frozen=True)
class SparkSessions:
    """How an engine makes Spark sessions, for the views and the code.

    Attributes
    ----------
    session : callable
        ``session(ctx, options)``: the Spark session to read ``ctx``'s item
        with, for a view.
    code_import : str
        The code's import of what ``code`` uses.
    code : callable
        ``code(ctx, options)``: the code's lines making the session,
        ``spark``.
    """

    session: Callable[[ItemContext, PySparkOptions], Any]
    code_import: str
    code: Callable[[ItemContext, PySparkOptions], str]


def _pyspark_session(ctx: ItemContext, options: PySparkOptions) -> Any:
    return spark_session(options.session_options)


def _pyspark_session_code(ctx: ItemContext, options: PySparkOptions) -> str:
    return spark_session_code(options)


PYSPARK_SESSIONS = SparkSessions(
    session=_pyspark_session,
    code_import="from pyspark.sql import SparkSession",
    code=_pyspark_session_code,
)


def spark_can_read(fmt: DataFormat, ctx: ItemContext, options: PySparkOptions) -> bool:
    """The actions' check, for the view and the code alike: whether Spark
    reads the item, by its URL's scheme as Spark names it
    (``PySparkOptions.supported_protocols``)."""
    if options.supported_protocols is None:
        return True
    scheme = spark_url(ctx.location.url).partition(":")[0].lower()
    return scheme in {p.lower() for p in options.supported_protocols}


def _spark_view(
    sessions: SparkSessions,
    ctx: ItemContext,
    options: PySparkOptions,
    read: Callable[[Any, str], Any],
    defaults: Mapping[str, Any] | None = None,
) -> View:
    """The data browser on ``read(reader, url)``, a Spark DataFrame: each
    page a Spark job."""
    spark = sessions.session(ctx, options)
    data = read(spark_reader(options, spark, defaults), _url(ctx))
    return QueryView(data=data, fetch=spark_rows)


# The code loading an item: {code_import}, then {note} (a comment line, or
# ""), {session}, the lines making ``spark``, and the read, ``spark.read``
# with {reader}, its options, and {read}, e.g. ".csv('s3a://b/a.csv')".
_CODE_TEMPLATE = cleandoc("""
    {code_import}

    {note}{session}
    df = spark.read{reader}{read}
    """)


def _spark_code(
    sessions: SparkSessions,
    ctx: ItemContext,
    options: PySparkOptions,
    call: str,
    *,
    defaults: Mapping[str, Any] | None = None,
    note: str = "",
) -> str:
    """The code loading the item into a DataFrame: the session, then
    ``spark.read``, its options and ``call`` of the URL, e.g. ".csv({url})"."""
    return _CODE_TEMPLATE.format(
        code_import=sessions.code_import,
        note=note,
        session=sessions.code(ctx, options),
        reader=spark_reader_code(options, defaults),
        read=call.format(url=repr(_url(ctx))),
    )


def spark_csv_view(
    sessions: SparkSessions,
    fmt: Csv,
    ctx: ItemContext,
    options: CsvByPySparkOptions,
    limits: ViewLimits,
) -> View:
    """CSV in the data browser, with the separator detected from the file's
    beginning, read through the explorer, unless the options give one."""
    defaults = {}
    if options.sep is None:
        text, _ = ctx.head_text(limits.max_bytes)
        defaults["sep"] = fmt.separator(ctx.name, text)
    return _spark_view(
        sessions, ctx, options, lambda reader, url: reader.csv(url), defaults
    )


def spark_csv_code(
    sessions: SparkSessions, fmt: Csv, ctx: ItemContext, options: CsvByPySparkOptions
) -> str:
    """CSV into a DataFrame, with the separator detected unless one is given."""
    defaults = {} if options.sep is not None else {"sep": fmt.code_separator(ctx)}
    return _spark_code(sessions, ctx, options, ".csv({url})", defaults=defaults)


def spark_json_lines_view(
    sessions: SparkSessions, ctx: ItemContext, options: JsonLinesByPySparkOptions
) -> View:
    """JSON Lines in the data browser."""
    return _spark_view(sessions, ctx, options, lambda reader, url: reader.json(url))


def spark_json_lines_code(
    sessions: SparkSessions, ctx: ItemContext, options: JsonLinesByPySparkOptions
) -> str:
    """JSON Lines into a DataFrame: Spark reads one record per line by
    default."""
    return _spark_code(sessions, ctx, options, ".json({url})")


def spark_parquet_view(
    sessions: SparkSessions, ctx: ItemContext, options: ParquetByPySparkOptions
) -> View:
    """A Parquet file or a folder of them in the data browser: Spark finds
    partitions itself."""
    return _spark_view(sessions, ctx, options, lambda reader, url: reader.parquet(url))


def spark_parquet_code(
    sessions: SparkSessions, ctx: ItemContext, options: ParquetByPySparkOptions
) -> str:
    """A Parquet file or a folder of them into a DataFrame."""
    return _spark_code(sessions, ctx, options, ".parquet({url})")


def spark_delta_view(
    sessions: SparkSessions, ctx: ItemContext, options: DeltaLakeByPySparkOptions
) -> View:
    """A Delta Lake table in the data browser."""
    return _spark_view(
        sessions, ctx, options, lambda reader, url: reader.format("delta").load(url)
    )


def spark_delta_code(
    sessions: SparkSessions, ctx: ItemContext, options: DeltaLakeByPySparkOptions
) -> str:
    """A Delta Lake table into a DataFrame. The session is obtained, not
    configured: Delta Lake's setup in Spark is left to the user."""
    note = "# Needs Delta Lake in the Spark session (Databricks has it)\n"
    return _spark_code(
        sessions, ctx, options, '.format("delta").load({url})', note=note
    )


AS_DATA_FRAME = "Load as DataFrame"


# Delta Lake: set up in the Spark session (on Databricks, it is).


@code(
    format=DeltaLake,
    engine=PySparkEngine,
    label=AS_DATA_FRAME,
    requires=(DeltaSpark(),),
    check=spark_can_read,
)
def delta_as_data_frame(ctx: ItemContext, options: DeltaLakeByPySparkOptions) -> str:
    """A Delta Lake table into a DataFrame."""
    return spark_delta_code(PYSPARK_SESSIONS, ctx, options)


@view(
    format=DeltaLake,
    engine=PySparkEngine,
    requires=(DeltaSpark(),),
    check=spark_can_read,
    code=delta_as_data_frame,
)
def delta_view(
    ctx: ItemContext,
    options: DeltaLakeByPySparkOptions,
) -> View:
    """A Delta Lake table in the data browser."""
    return spark_delta_view(PYSPARK_SESSIONS, ctx, options)


@code(format=Parquet, engine=PySparkEngine, label=AS_DATA_FRAME, check=spark_can_read)
def parquet_as_data_frame(ctx: ItemContext, options: ParquetByPySparkOptions) -> str:
    """A Parquet file or a folder of them into a DataFrame."""
    return spark_parquet_code(PYSPARK_SESSIONS, ctx, options)


@view(
    format=Parquet,
    engine=PySparkEngine,
    check=spark_can_read,
    code=parquet_as_data_frame,
)
def parquet_view(
    ctx: ItemContext,
    options: ParquetByPySparkOptions,
) -> View:
    """A Parquet file or a folder of them in the data browser."""
    return spark_parquet_view(PYSPARK_SESSIONS, ctx, options)


@code(format=Csv, engine=PySparkEngine, label=AS_DATA_FRAME, check=spark_can_read)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByPySparkOptions) -> str:
    """CSV into a DataFrame."""
    return spark_csv_code(PYSPARK_SESSIONS, fmt, ctx, options)


@view(format=Csv, engine=PySparkEngine, check=spark_can_read, code=csv_as_data_frame)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByPySparkOptions, limits: ViewLimits
) -> View:
    """CSV in the data browser."""
    return spark_csv_view(PYSPARK_SESSIONS, fmt, ctx, options, limits)


@code(format=JsonLines, engine=PySparkEngine, label=AS_DATA_FRAME, check=spark_can_read)
def json_lines_as_data_frame(
    ctx: ItemContext, options: JsonLinesByPySparkOptions
) -> str:
    """JSON Lines into a DataFrame."""
    return spark_json_lines_code(PYSPARK_SESSIONS, ctx, options)


@view(
    format=JsonLines,
    engine=PySparkEngine,
    check=spark_can_read,
    code=json_lines_as_data_frame,
)
def json_lines_view(
    ctx: ItemContext,
    options: JsonLinesByPySparkOptions,
) -> View:
    """JSON Lines in the data browser."""
    return spark_json_lines_view(PYSPARK_SESSIONS, ctx, options)


# In the order tried.
PYSPARK_ACTIONS = register_actions(
    delta_view,
    delta_as_data_frame,
    parquet_view,
    parquet_as_data_frame,
    csv_view,
    csv_as_data_frame,
    json_lines_view,
    json_lines_as_data_frame,
)
