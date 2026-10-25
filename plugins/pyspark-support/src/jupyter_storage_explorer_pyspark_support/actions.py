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

from dataclasses import dataclass, field, fields
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

import narwhals as nw

from jupyter_storage_explorer.formats.actions import code, register_actions, view
from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.packages import PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import SupportOptions, format_kwargs
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.view import QueryView, View, ViewLimits

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from dataclasses import Field

# Spark (Hadoop) names for storage URLs: TLS "abfss" for Azure, as Spark
# expects it (storage accounts usually require secure transfer); "s3a", the
# S3 connector of open-source Hadoop (Databricks and EMR accept it too).
_SPARK_SCHEMES = {"abfs": "abfss", "az": "abfss", "s3": "s3a"}


# The engine's libraries, and those only Spark uses (the support libraries
# several engines use are the core's: jupyter_storage_explorer.formats.packages).


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
        return active
    builder = SparkSession.builder
    for key, value in (session_options or {}).items():
        builder = builder.config(key, value)
    return builder.getOrCreate()


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


# The fields of PySparkOptions that are not one reader option each.
_NOT_READER_OPTIONS = frozenset(
    {"session_options", "reader_options", "supported_protocols"}
)

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
class PySparkOptions(SupportOptions):
    """The options of the formats Spark reads, for the data browser and the
    code. Each format's subclass adds its reader options as fields
    (``CsvByPySparkOptions``, ...): None, their default, leaves the option to
    Spark.

    Attributes
    ----------
    session_options : mapping or None, default None
        Spark configuration given to ``SparkSession.builder.config(key,
        value)``, e.g. Delta Lake's ``{"spark.sql.extensions":
        "io.delta.sql.DeltaSparkSessionExtension", ...}`` or storage access
        (``"spark.hadoop.fs.azure.account.key.<account>.dfs.core.windows.net"``).
        With a session already running, only what Spark can change at run time
        applies. In the code, those that look like credentials are left out.
    reader_options : mapping or None, default None
        Options given to the reader, ``spark.read.option(key, value)``, e.g.
        Spark's generic file source options (``{"recursiveFileLookup":
        True}``) or those of a newer Spark; they override the fields and the
        defaults (for CSV, the separator detected).
    supported_protocols : sequence of str or None, default SPARK_PROTOCOLS
        The URL schemes Spark reads, as Spark names them (e.g. "s3a",
        "abfss", "dbfs"): items elsewhere, e.g. on SFTP or in fsspec's memory
        filesystem, are neither viewed nor given code with Spark. None for
        any.
    """

    session_options: Mapping[str, Any] | None = None
    reader_options: Mapping[str, Any] | None = None
    supported_protocols: Sequence[str] | None = SPARK_PROTOCOLS


# What the actions do with the options: functions of them, so that the
# options stay data.


def spark_reader_options(options: PySparkOptions) -> dict[str, Any]:
    """The reader options the fields of ``options`` set (those not None), by
    Spark's names.

    Parameters
    ----------
    options : PySparkOptions
        A format's options, e.g. ``CsvByPySparkOptions``.

    Returns
    -------
    dict
        E.g. ``{"header": True, "inferSchema": True}``.
    """
    return {
        _spark_name(f): value
        for f in fields(options)
        if f.name not in _NOT_READER_OPTIONS
        and (value := getattr(options, f.name)) is not None
    }


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
        defaults or {}, spark_reader_options(options), options.reader_options or {}
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
    shown = {
        _spark_name(f): value
        for f in fields(options)
        if f.name not in _NOT_READER_OPTIONS
        and (value := options.code_value(f.name)) is not None
    }
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
# is the option of its name in camel case unless SPARK_NAME says otherwise;
# the plugin's README has their tables: keep them in step.


@dataclass(frozen=True, kw_only=True)
class CsvByPySparkOptions(PySparkOptions):
    """Spark's CSV reader options (``spark.read.csv``), besides the session's
    and ``reader_options``.

    Each field is the option of its name in camel case (``null_value`` is
    ``nullValue``; ``timestamp_ntz_format``, ``timestampNTZFormat``),
    documented in Spark's "CSV Files"; None leaves it to Spark. The plugin's
    README lists them.

    Attributes
    ----------
    sep : str or None, default None
        The separator; None for the one detected from the file's beginning
        (and its extension, e.g. tabs for ".tsv").
    header : bool, default True
        Whether the first line names the columns (Spark's default is False).
    infer_schema : bool, default True
        Whether the columns' types are inferred, an extra pass over the data
        (Spark's default is False: strings).
    """

    sep: str | None = None
    encoding: str | None = None
    quote: str | None = None
    escape: str | None = None
    comment: str | None = None
    header: bool | None = True
    infer_schema: bool | None = True
    prefer_date: bool | None = None
    enforce_schema: bool | None = None
    ignore_leading_white_space: bool | None = None
    ignore_trailing_white_space: bool | None = None
    null_value: str | None = None
    nan_value: str | None = None
    positive_inf: str | None = None
    negative_inf: str | None = None
    date_format: str | None = None
    timestamp_format: str | None = None
    timestamp_ntz_format: str | None = field(
        default=None, metadata={SPARK_NAME: "timestampNTZFormat"}
    )
    enable_date_time_parsing_fallback: bool | None = None
    max_columns: int | None = None
    max_chars_per_column: int | None = None
    mode: str | None = None
    column_name_of_corrupt_record: str | None = None
    multi_line: bool | None = None
    char_to_escape_quote_escaping: str | None = None
    sampling_ratio: float | None = None
    empty_value: str | None = None
    locale: str | None = None
    line_sep: str | None = None
    unescaped_quote_handling: str | None = None
    time_zone: str | None = None


@dataclass(frozen=True, kw_only=True)
class JsonLinesByPySparkOptions(PySparkOptions):
    """Spark's JSON reader options (``spark.read.json``), besides the
    session's and ``reader_options``.

    Each field is the option of its name in camel case
    (``primitives_as_string`` is ``primitivesAsString``;
    ``timestamp_ntz_format``, ``timestampNTZFormat``), documented in Spark's
    "JSON Files"; None leaves it to Spark. The plugin's README lists them.
    """

    time_zone: str | None = None
    primitives_as_string: bool | None = None
    prefers_decimal: bool | None = None
    allow_comments: bool | None = None
    allow_unquoted_field_names: bool | None = None
    allow_single_quotes: bool | None = None
    allow_numeric_leading_zeros: bool | None = None
    allow_backslash_escaping_any_character: bool | None = None
    mode: str | None = None
    column_name_of_corrupt_record: str | None = None
    date_format: str | None = None
    timestamp_format: str | None = None
    timestamp_ntz_format: str | None = field(
        default=None, metadata={SPARK_NAME: "timestampNTZFormat"}
    )
    enable_date_time_parsing_fallback: bool | None = None
    multi_line: bool | None = None
    allow_unquoted_control_chars: bool | None = None
    encoding: str | None = None
    line_sep: str | None = None
    sampling_ratio: float | None = None
    drop_field_if_all_null: bool | None = None
    locale: str | None = None
    allow_non_numeric_numbers: bool | None = None
    use_unsafe_row: bool | None = None


@dataclass(frozen=True, kw_only=True)
class ParquetByPySparkOptions(PySparkOptions):
    """Spark's Parquet reader options (``spark.read.parquet``), besides the
    session's and ``reader_options``.

    Each field is the option of its name in camel case (``merge_schema`` is
    ``mergeSchema``), documented in Spark's "Parquet Files"; None leaves it
    to Spark (its session's configuration). The plugin's README lists them.
    """

    datetime_rebase_mode: str | None = None
    int96_rebase_mode: str | None = None
    merge_schema: bool | None = None


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByPySparkOptions(PySparkOptions):
    """Delta Lake's reader options for time travel, besides the session's and
    ``reader_options``: a table's earlier version.

    Attributes
    ----------
    timestamp_as_of : str or None, default None
        ``timestampAsOf``: the table as of a date or a timestamp, e.g.
        "2019-01-01" or "2019-01-01T00:00:00.000Z".
    version_as_of : int or None, default None
        ``versionAsOf``: the table's version of that number (``DESCRIBE
        HISTORY`` lists them).
    """

    timestamp_as_of: str | None = None
    version_as_of: int | None = None


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
    name=AS_DATA_FRAME,
    requires=(DeltaSpark(),),
    check=spark_can_read,
)
def delta_as_data_frame(
    fmt: DeltaLake, ctx: ItemContext, options: DeltaLakeByPySparkOptions
) -> str:
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
    fmt: DeltaLake,
    ctx: ItemContext,
    options: DeltaLakeByPySparkOptions,
    limits: ViewLimits,
) -> View:
    """A Delta Lake table in the data browser."""
    return spark_delta_view(PYSPARK_SESSIONS, ctx, options)


@code(format=Parquet, engine=PySparkEngine, name=AS_DATA_FRAME, check=spark_can_read)
def parquet_as_data_frame(
    fmt: Parquet, ctx: ItemContext, options: ParquetByPySparkOptions
) -> str:
    """A Parquet file or a folder of them into a DataFrame."""
    return spark_parquet_code(PYSPARK_SESSIONS, ctx, options)


@view(
    format=Parquet,
    engine=PySparkEngine,
    check=spark_can_read,
    code=parquet_as_data_frame,
)
def parquet_view(
    fmt: Parquet,
    ctx: ItemContext,
    options: ParquetByPySparkOptions,
    limits: ViewLimits,
) -> View:
    """A Parquet file or a folder of them in the data browser."""
    return spark_parquet_view(PYSPARK_SESSIONS, ctx, options)


@code(format=Csv, engine=PySparkEngine, name=AS_DATA_FRAME, check=spark_can_read)
def csv_as_data_frame(fmt: Csv, ctx: ItemContext, options: CsvByPySparkOptions) -> str:
    """CSV into a DataFrame."""
    return spark_csv_code(PYSPARK_SESSIONS, fmt, ctx, options)


@view(format=Csv, engine=PySparkEngine, check=spark_can_read, code=csv_as_data_frame)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByPySparkOptions, limits: ViewLimits
) -> View:
    """CSV in the data browser."""
    return spark_csv_view(PYSPARK_SESSIONS, fmt, ctx, options, limits)


@code(format=JsonLines, engine=PySparkEngine, name=AS_DATA_FRAME, check=spark_can_read)
def json_lines_as_data_frame(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByPySparkOptions
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
    fmt: JsonLines,
    ctx: ItemContext,
    options: JsonLinesByPySparkOptions,
    limits: ViewLimits,
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
