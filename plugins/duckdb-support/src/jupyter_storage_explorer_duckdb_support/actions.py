"""Formats handled with DuckDB: the data browser and load code, and DuckDB's
own database files.

How DuckDB reaches an item depends on the storage and the format, as
measured with DuckDB 1.5 (the plugin's README says it for users):

- Local files, and the storages whose URL schemes ``url_schemes`` lists,
  DuckDB reads by URL itself. Elsewhere, it would need its extensions and
  their secrets, which the explorer cannot check.
- Parquet elsewhere: through the explorer's filesystem, registered on the
  view's connection as it is, by its own URL of the item. DuckDB reads it
  lazily so: the footer, then only the row groups a query needs. It reads a
  registered filesystem before its own readers (httpfs' ``s3://`` too), but
  fails on one without ``modified`` (fsspec's HTTP and zip), refused.
- CSV and JSON Lines elsewhere: DuckDB reads a whole file again for each
  filter, sort or count, and a buffer of 32 MB for the first rows. So the
  file is copied to the kernel's disk first (``local_file_cache``), or, when
  large, only its beginning is read into memory, as the user chooses.
- Delta Lake tables: DuckDB's delta extension (``delta_scan``) reads them
  lazily, but only by URL. ``deltalake``'s PyArrow dataset, which could read
  any storage, is not lazy for DuckDB: it reads the whole table for the
  first rows. So other storages' tables are refused.
- DuckDB databases: DuckDB opens only local files, also with a filesystem
  registered. Other storages' are copied to the kernel's disk first.

Each format has a view and a code action, registered in order in
``DUCKDB_ACTIONS``. duckdb is imported inside the functions, so that the
plugin loads without it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from fsspec.implementations.dirfs import DirFileSystem
from fsspec.spec import AbstractFileSystem

from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.actions import (
    ActionOptions,
    code,
    register_actions,
    view,
)
from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.local_files import local_file_cache
from jupyter_storage_explorer.formats.packages import PyArrow, PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.views import (
    Leaf,
    Node,
    QueryView,
    TableSetView,
    TextView,
    View,
    ViewLimits,
    ViewWithChoice,
    ViewWithConfirmation,
)
from jupyter_storage_explorer.util import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    format_arguments,
    format_kwargs,
    format_size,
    secret_dict_field,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

AS_RELATION = "Load as relation"
OPEN_DATABASE = "Open the database"

# How long a local copy no view uses is kept, in seconds, so that viewing the
# file again soon reuses it.
_COPY_KEPT = 600


# The engine's library. PyArrow, which the data browser collects DuckDB's
# results into, is the core's (jupyter_storage_explorer.formats.packages).


class DuckDB(PythonPackage):
    package = "duckdb"
    import_name = "duckdb"


class DuckDBEngine(Engine):
    key = "duckdb"
    label = "DuckDB"
    requirements = (DuckDB(),)


# A database's icon in the explorer's list: a plain cylinder, in
# JupyterLab's grey.
_DATABASE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
    ' stroke="#616161" stroke-width="2" stroke-linecap="round">'
    '<ellipse cx="12" cy="5" rx="8" ry="3"/>'
    '<path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
    '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>'
)


class DuckDBDatabase(DataFormat):
    """DuckDB's database files, confirmed by their signature: ".db" is
    SQLite's too, and any name can hold a database."""

    name = "duckdb"
    label = "DuckDB database"
    extensions = (".duckdb", ".ddb", ".db")
    file_icon = ("database", _DATABASE_SVG)
    # A database starts with an 8-byte checksum, then "DUCK".
    sniff_bytes = 12

    def sniff(self, ctx: ItemContext, head: bytes) -> bool:
        """Whether the file starts as DuckDB's databases do.

        Parameters
        ----------
        ctx : ItemContext
            The file.
        head : bytes
            Its first bytes.

        Returns
        -------
        bool
        """
        return head[8:12] == b"DUCK"


# Keys of DuckDB's configuration and of fsspec's storage options that are
# credentials: never in generated code.
_CONFIG_SECRETS = (
    "s3_access_key_id",
    "s3_secret_access_key",
    "s3_session_token",
    "azure_storage_connection_string",
    "motherduck_token",
)
_FSSPEC_SECRETS = (
    "account_key",
    "sas_token",
    "connection_string",
    "client_secret",
    "key",
    "secret",
    "token",
    "password",
)


@dataclass(frozen=True, kw_only=True)
class DuckDBOptions(ActionOptions):
    """The options of every DuckDB action: the connection, and how DuckDB
    reaches the storage.

    Attributes
    ----------
    config : mapping or None, default None
        ``duckdb.connect``'s ``config``, e.g. ``{"threads": 4, "memory_limit":
        "2GB"}``, for the data browser and the code; in the code, keys that
        look like credentials are left out.
    url_schemes : sequence of str, default ()
        The URL schemes of the storages DuckDB reads itself, by URL, e.g.
        ``["s3"]`` once its httpfs extension and secrets reach S3. Local files
        are always read by URL. Other storages are read through the explorer's
        filesystem, or copied to the kernel's disk.
    fsspec_storage_options : mapping or None, default None
        ``fsspec.url_to_fs``'s keyword arguments in the code, on storages
        DuckDB does not read itself; those that look like credentials are
        left out.
    """

    config: Mapping[str, Any] | None = secret_dict_field(
        default=None, secret_keys=_CONFIG_SECRETS
    )
    url_schemes: Sequence[str] = ()
    fsspec_storage_options: Mapping[str, Any] | None = secret_dict_field(
        default=None, secret_keys=_FSSPEC_SECRETS
    )

    def connect_kwargs(self) -> dict[str, Any]:
        """``duckdb.connect``'s keyword arguments in the data browser."""
        return {"config": dict(self.config)} if self.config else {}

    def connect_code(self) -> str:
        """``duckdb.connect``'s keyword arguments in the code, after others."""
        return format_kwargs(config=self.code_value("config"))

    def fsspec_kwargs(self) -> str:
        """``fsspec``'s keyword arguments in the code, after the URL."""
        return format_kwargs(**(self.code_value("fsspec_storage_options") or {}))


# Each format's options below are its DuckDB reader's arguments, of the same
# names (DuckDB's Python API: read_parquet, read_csv, read_json; delta_scan's
# named parameters), but the source and the arguments of several files read
# together (union_by_name, hive_types, ...), as the formats are single files
# but Parquet. LIBRARY_DEFAULT leaves one to DuckDB. The plugin's README has
# their tables: keep them in step.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class ParquetByDuckDBOptions(DuckDBOptions):
    """DuckDB's ``read_parquet`` arguments: unset ones are left to DuckDB,
    but ``hive_partitioning``, set by the folders detected. The plugin's
    README lists them."""

    binary_as_string: bool | _Default = LIBRARY_DEFAULT
    file_row_number: bool | _Default = LIBRARY_DEFAULT
    filename: bool | _Default = LIBRARY_DEFAULT
    hive_partitioning: bool | _Default = LIBRARY_DEFAULT
    union_by_name: bool | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class CsvByDuckDBOptions(DuckDBOptions):
    """DuckDB's ``read_csv`` arguments: unset ones are left to DuckDB, whose
    sniffer detects the dialect and the types. The plugin's README lists
    them."""

    header: bool | int | _Default = LIBRARY_DEFAULT
    sep: str | _Default = LIBRARY_DEFAULT
    quotechar: str | _Default = LIBRARY_DEFAULT
    escapechar: str | _Default = LIBRARY_DEFAULT
    comment: str | _Default = LIBRARY_DEFAULT
    lineterminator: str | _Default = LIBRARY_DEFAULT
    encoding: str | _Default = LIBRARY_DEFAULT
    compression: str | _Default = LIBRARY_DEFAULT
    skiprows: int | _Default = LIBRARY_DEFAULT
    names: Sequence[str] | _Default = LIBRARY_DEFAULT
    columns: Mapping[str, str] | _Default = LIBRARY_DEFAULT
    dtype: Mapping[str, str] | Sequence[str] | _Default = LIBRARY_DEFAULT
    na_values: str | Sequence[str] | _Default = LIBRARY_DEFAULT
    force_not_null: Sequence[str] | _Default = LIBRARY_DEFAULT
    allow_quoted_nulls: bool | _Default = LIBRARY_DEFAULT
    all_varchar: bool | _Default = LIBRARY_DEFAULT
    auto_detect: bool | _Default = LIBRARY_DEFAULT
    auto_type_candidates: Sequence[str] | _Default = LIBRARY_DEFAULT
    sample_size: int | _Default = LIBRARY_DEFAULT
    date_format: str | _Default = LIBRARY_DEFAULT
    timestamp_format: str | _Default = LIBRARY_DEFAULT
    decimal: str | _Default = LIBRARY_DEFAULT
    thousands: str | _Default = LIBRARY_DEFAULT
    normalize_names: bool | _Default = LIBRARY_DEFAULT
    null_padding: bool | _Default = LIBRARY_DEFAULT
    ignore_errors: bool | _Default = LIBRARY_DEFAULT
    strict_mode: bool | _Default = LIBRARY_DEFAULT
    max_line_size: int | _Default = LIBRARY_DEFAULT
    buffer_size: int | _Default = LIBRARY_DEFAULT
    parallel: bool | _Default = LIBRARY_DEFAULT
    store_rejects: bool | _Default = LIBRARY_DEFAULT
    rejects_table: str | _Default = LIBRARY_DEFAULT
    rejects_scan: str | _Default = LIBRARY_DEFAULT
    rejects_limit: int | _Default = LIBRARY_DEFAULT
    filename: bool | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonLinesByDuckDBOptions(DuckDBOptions):
    """DuckDB's ``read_json`` arguments: unset ones are left to DuckDB, but
    ``format``, "newline_delimited". The plugin's README lists them."""

    columns: Mapping[str, str] | _Default = LIBRARY_DEFAULT
    format: str | _Default = LIBRARY_DEFAULT
    records: str | _Default = LIBRARY_DEFAULT
    sample_size: int | _Default = LIBRARY_DEFAULT
    maximum_depth: int | _Default = LIBRARY_DEFAULT
    maximum_object_size: int | _Default = LIBRARY_DEFAULT
    date_format: str | _Default = LIBRARY_DEFAULT
    timestamp_format: str | _Default = LIBRARY_DEFAULT
    compression: str | _Default = LIBRARY_DEFAULT
    ignore_errors: bool | _Default = LIBRARY_DEFAULT
    convert_strings_to_integers: bool | _Default = LIBRARY_DEFAULT
    field_appearance_threshold: float | _Default = LIBRARY_DEFAULT
    map_inference_threshold: int | _Default = LIBRARY_DEFAULT
    filename: bool | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class DeltaLakeByDuckDBOptions(DuckDBOptions):
    """The named parameters of ``delta_scan``, DuckDB's delta extension's:
    unset ones are left to DuckDB. The plugin's README lists them."""

    version: int | _Default = LIBRARY_DEFAULT
    binary_as_string: bool | _Default = LIBRARY_DEFAULT
    file_row_number: bool | _Default = LIBRARY_DEFAULT
    filename: bool | _Default = LIBRARY_DEFAULT


def _readable_registered(fs: AbstractFileSystem) -> bool:
    """Whether DuckDB reads through ``fs`` registered on a connection: it
    calls ``modified`` for each file, and fails where the filesystem has none
    (e.g. fsspec's HTTP and zip filesystems). A ``DirFileSystem``'s is that
    of the filesystem it wraps."""
    while isinstance(fs, DirFileSystem):
        fs = fs.fs
    return type(fs).modified is not AbstractFileSystem.modified


# The URL schemes DuckDB reads itself with its extensions (httpfs, azure,
# hf), once configured: what code reads by URL. abfs:// it reads as abfss://.
_DUCKDB_SCHEMES = frozenset(
    {
        "s3",
        "s3a",
        "s3n",
        "r2",
        "gs",
        "gcs",
        "az",
        "azure",
        "abfs",
        "abfss",
        "http",
        "https",
        "hf",
    }
)


def _scheme(ctx: ItemContext) -> str:
    return ctx.location.url.partition(":")[0].lower()


def _read_by_duckdb(fmt: DataFormat, ctx: ItemContext, options: DuckDBOptions) -> bool:
    """Whether the views read the item by URL, DuckDB reading the storage
    itself: a local file, or one of ``options.url_schemes``. Elsewhere they
    read it through the explorer's filesystem. Also the check of Delta Lake's
    view: ``delta_scan`` reads no registered filesystem."""
    if isinstance(ctx.location, LocalLocation):
        return True
    return _scheme(ctx) in {s.lower() for s in options.url_schemes}


def _code_read_by_duckdb(
    fmt: DataFormat, ctx: ItemContext, options: DuckDBOptions
) -> bool:
    """Whether the code reads the item by URL: where the views do, and on
    the storages DuckDB's extensions reach. Elsewhere it registers fsspec's
    filesystem. Also the check of Delta Lake's code, which reads by URL
    only."""
    return _read_by_duckdb(fmt, ctx, options) or _scheme(ctx) in _DUCKDB_SCHEMES


def _duckdb_url(ctx: ItemContext) -> str:
    """The item's URL as DuckDB reads it: a local file's plain path, and
    Azure's ``abfss://`` for ``abfs://``, which DuckDB does not take."""
    url = ctx.url_or_local_path
    if not isinstance(ctx.location, LocalLocation) and url.startswith("abfs://"):
        url = "abfss://" + url.removeprefix("abfs://")
    return url


def _sql_literal(value: Any) -> str:
    """``value`` as a SQL literal of DuckDB."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _quoted(*names: str) -> str:
    """A qualified name of DuckDB, each part quoted, e.g. ``"sales"."orders"``."""
    return ".".join('"' + name.replace('"', '""') + '"' for name in names)


# Every action reads with DuckDB, on a connection of each view's own, closed
# with it. The data browser collects DuckDB's results into PyArrow tables
# (narwhals' default for DuckDB): all of them require PyArrow.
_REQUIRES = (PyArrow(),)


def _connect(options: DuckDBOptions, database: str = ":memory:", **kwargs: Any) -> Any:
    import duckdb

    return duckdb.connect(database, **kwargs, **options.connect_kwargs())


def _query_view(con: Any, read: Callable[[Any], Any], **kwargs: Any) -> View:
    """A ``QueryView`` of ``read(con)``, closing the connection with the
    view, or at once if ``read`` fails."""
    try:
        view = QueryView(data=read(con), **kwargs)
    except BaseException:
        con.close()
        raise
    view.on_close(lambda view: con.close())
    return view


# The code reading a URL into a relation: by URL, or through fsspec's
# filesystem registered with DuckDB.
_RELATION_BY_URL = cleandoc("""
    import duckdb

    con = duckdb.connect({connect})
    rel = con.{reader}({url!r}{kwargs})
    """)
_RELATION_THROUGH_FSSPEC = cleandoc("""
    import duckdb
    import fsspec

    con = duckdb.connect({connect})
    fs, _ = fsspec.url_to_fs({url!r}{fsspec_kwargs})
    con.register_filesystem(fs)
    rel = con.{reader}({url!r}{kwargs})
    """)


def _relation_code(
    reader: str, url: str, kwargs: str, options: DuckDBOptions, *, by_url: bool
) -> str:
    """The code reading ``url`` into a relation with the connection's
    ``reader`` (e.g. "read_csv"): by URL, or through fsspec's filesystem
    registered with DuckDB."""
    template = _RELATION_BY_URL if by_url else _RELATION_THROUGH_FSSPEC
    return template.format(
        connect=options.connect_code().removeprefix(", "),
        reader=reader,
        url=url,
        kwargs=kwargs,
        fsspec_kwargs=options.fsspec_kwargs(),
    )


# Parquet files and folders: lazily by URL where DuckDB reads the storage
# itself; elsewhere, as lazily, through the explorer's filesystem, where
# DuckDB can read through it.


def _can_view_parquet(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDuckDBOptions
) -> bool:
    """Whether the view reaches the item: by URL, or through the explorer's
    filesystem where DuckDB reads it (``modified``)."""
    return _read_by_duckdb(fmt, ctx, options) or _readable_registered(ctx.fs)


def _parquet_data_url(fmt: Parquet, ctx: ItemContext, url: str) -> str:
    """The data files of the item at ``url``, its URL as DuckDB reads it: a
    file's URL, or a glob of a folder's data files."""
    url = fmt.data_url(ctx, url)
    if ctx.is_dir and fmt.layout(ctx).files == "*":
        # Data files without an extension (Hive's): not "_SUCCESS" or
        # ".crc" checksums, which DuckDB would read.
        url = url.removesuffix("*") + "[!_.]*"
    return url


@code(format=Parquet, engine=DuckDBEngine, label=AS_RELATION, requires=_REQUIRES)
def parquet_as_relation(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDuckDBOptions
) -> str:
    """The code reading the file or folder into a relation, on any storage."""
    partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
    arguments = {"hive_partitioning": True} if partitioned else {}
    arguments.update(options.code_arguments())
    by_url = _code_read_by_duckdb(fmt, ctx, options)
    url = _duckdb_url(ctx) if by_url else ctx.location.url
    return _relation_code(
        "read_parquet",
        _parquet_data_url(fmt, ctx, url),
        format_arguments(arguments),
        options,
        by_url=by_url,
    )


@view(
    format=Parquet,
    engine=DuckDBEngine,
    requires=_REQUIRES,
    check=_can_view_parquet,
    code=parquet_as_relation,
)
def parquet_view(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDuckDBOptions
) -> View:
    """A relation of the Parquet file, or of the folder's data files, with a
    folder's partition columns. It takes no ``limits``: DuckDB reads only
    what the data browser asks."""
    partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
    arguments = {"hive_partitioning": partitioned, **options.arguments()}

    def read(con: Any) -> Any:
        if _read_by_duckdb(fmt, ctx, options):
            url = _duckdb_url(ctx)
        else:
            # The explorer's filesystem as it is, on this connection only:
            # DuckDB reads it before its own readers (e.g. httpfs' s3://),
            # and its own URL of the item, not the location's.
            con.register_filesystem(ctx.fs)
            url = ctx.fs.unstrip_protocol(ctx.path)
        return con.read_parquet(_parquet_data_url(fmt, ctx, url), **arguments)

    return _query_view(_connect(options), read)


# Text formats of files (CSV, JSON Lines), which DuckDB reads whole for each
# filter, sort or count: by URL where DuckDB reads the storage itself;
# elsewhere from a copy on the kernel's disk, or the file's beginning in
# memory, as the user chooses for a large file.

# JSON Lines' own argument, rather than DuckDB's detection, which also takes
# a JSON array.
_JSON_LINES_DEFAULTS: Mapping[str, Any] = {"format": "newline_delimited"}


def _text_view(
    reader: str,
    defaults: Mapping[str, Any],
    fmt: DataFormat,
    ctx: ItemContext,
    options: DuckDBOptions,
    *,
    limits: ViewLimits,
) -> View:
    """A relation of the file, read by the connection's ``reader`` with
    ``defaults``, then the options' arguments.

    Off the storages DuckDB reads itself, a file larger than
    ``limits.max_whole_file_bytes`` and not copied yet is read once the user
    chooses: copied to the kernel's disk whole, or its first bytes up to that
    size, cut after their last line, read into memory."""

    def read(con: Any, source: Any) -> Any:
        return getattr(con, reader)(source, **{**defaults, **options.arguments()})

    if _read_by_duckdb(fmt, ctx, options):
        url = _duckdb_url(ctx)
        return _query_view(_connect(options), lambda con: read(con, url))
    cache = local_file_cache()

    def copied() -> View:
        path = cache.get(ctx).as_posix()
        try:
            view = _query_view(_connect(options), lambda con: read(con, path))
        except BaseException:
            cache.release(ctx.location, delay=_COPY_KEPT)
            raise
        view.on_close(lambda view: cache.release(ctx.location, delay=_COPY_KEPT))
        return view

    def first(size: int) -> View:
        with ctx.fs.open(ctx.path, "rb") as f:
            data = f.read(size + 1)
        cut = len(data) > size
        if cut:
            data = data[: data.rfind(b"\n", 0, size) + 1] or data[:size]
        return _query_view(
            _connect(options), lambda con: read(con, io.BytesIO(data)), more=cut
        )

    size = ctx.size
    limit = limits.max_whole_file_bytes
    if cache.status(ctx) == "cached" or (size is not None and size <= limit):
        return copied()
    whole = f"The whole file ({format_size(size)})" if size else "The whole file"
    return ViewWithChoice(
        message=(
            "DuckDB cannot read this storage itself, and reads the whole file "
            "for each query: the file is copied to the kernel's disk first, "
            "or its beginning read into memory."
        ),
        choices={f"Its first {format_size(limit)}": limit, whole: None},
        factory=lambda size: copied() if size is None else first(size),
        style="button",
        with_cancel=True,
    )


def _text_code(
    reader: str,
    defaults: Mapping[str, Any],
    fmt: DataFormat,
    ctx: ItemContext,
    options: DuckDBOptions,
) -> str:
    """The code reading the file into a relation with the connection's
    ``reader``."""
    by_url = _code_read_by_duckdb(fmt, ctx, options)
    return _relation_code(
        reader,
        _duckdb_url(ctx) if by_url else ctx.location.url,
        format_arguments({**defaults, **options.code_arguments()}),
        options,
        by_url=by_url,
    )


@code(format=Csv, engine=DuckDBEngine, label=AS_RELATION, requires=_REQUIRES)
def csv_as_relation(fmt: Csv, ctx: ItemContext, options: CsvByDuckDBOptions) -> str:
    """The code reading the CSV file into a relation."""
    return _text_code("read_csv", {}, fmt, ctx, options)


@view(format=Csv, engine=DuckDBEngine, requires=_REQUIRES, code=csv_as_relation)
def csv_view(
    fmt: Csv, ctx: ItemContext, options: CsvByDuckDBOptions, limits: ViewLimits
) -> View:
    """CSV files in the data browser: DuckDB's sniffer detects the dialect."""
    return _text_view("read_csv", {}, fmt, ctx, options, limits=limits)


@code(format=JsonLines, engine=DuckDBEngine, label=AS_RELATION, requires=_REQUIRES)
def json_lines_as_relation(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByDuckDBOptions
) -> str:
    """The code reading the JSON Lines file into a relation."""
    return _text_code("read_json", _JSON_LINES_DEFAULTS, fmt, ctx, options)


@view(
    format=JsonLines,
    engine=DuckDBEngine,
    requires=_REQUIRES,
    code=json_lines_as_relation,
)
def json_lines_view(
    fmt: JsonLines,
    ctx: ItemContext,
    options: JsonLinesByDuckDBOptions,
    limits: ViewLimits,
) -> View:
    """JSON Lines files in the data browser."""
    return _text_view(
        "read_json", _JSON_LINES_DEFAULTS, fmt, ctx, options, limits=limits
    )


# Delta Lake tables with DuckDB's delta extension, by URL only: locally, and
# on the storages DuckDB reads itself (``url_schemes``; in the code, those its
# extensions reach). DuckDB installs and loads the extension at the first
# query, unless its settings forbid it.

_DELTA_CODE = cleandoc("""
    import duckdb

    con = duckdb.connect({connect})
    rel = con.sql({query!r})
    """)


def _delta_query(ctx: ItemContext, options: DeltaLakeByDuckDBOptions) -> str:
    parameters = "".join(
        f", {name} := {_sql_literal(value)}"
        for name, value in options.arguments().items()
    )
    return f"select * from delta_scan({_sql_literal(_duckdb_url(ctx))}{parameters})"


@code(
    format=DeltaLake,
    engine=DuckDBEngine,
    label=AS_RELATION,
    requires=_REQUIRES,
    check=_code_read_by_duckdb,
)
def delta_as_relation(ctx: ItemContext, options: DeltaLakeByDuckDBOptions) -> str:
    """The code reading the table into a relation, by ``delta_scan``."""
    return _DELTA_CODE.format(
        connect=options.connect_code().removeprefix(", "),
        query=_delta_query(ctx, options),
    )


@view(
    format=DeltaLake,
    engine=DuckDBEngine,
    requires=_REQUIRES,
    check=_read_by_duckdb,
    code=delta_as_relation,
)
def delta_view(
    ctx: ItemContext,
    options: DeltaLakeByDuckDBOptions,
) -> View:
    """A relation of the table, by ``delta_scan``. It takes no ``limits``:
    DuckDB reads only what the data browser asks."""
    query = _delta_query(ctx, options)
    return _query_view(_connect(options), lambda con: con.sql(query))


# DuckDB's database files: their tables and views in the data browser, and
# code opening them. DuckDB opens only local files, also with a filesystem
# registered: other storages' are copied to the kernel's disk first, after
# asking for a large one.


def _table_nodes(tables: Sequence[tuple[str, str]]) -> list[Node]:
    """A database's tables and views, by schema, each with a database's
    icon; without the schema when there is only one."""
    schemas = sorted({schema for schema, _ in tables})
    if len(schemas) == 1:
        return [Leaf(label=name, id=_quoted(schema, name)) for schema, name in tables]
    return [
        Node(
            label=schema,
            children=[
                Leaf(label=name, id=_quoted(schema, name))
                for s, name in tables
                if s == schema
            ],
            icon="database",
        )
        for schema in schemas
    ]


# The code opening a database read only: a local file by its path; a remote
# one downloaded once by fsspec.
_LOCAL_DATABASE_CODE = cleandoc("""
    import duckdb

    con = duckdb.connect({path!r}, read_only=True{connect})
    con.sql('show all tables')
    """)
_REMOTE_DATABASE_CODE = cleandoc("""
    import duckdb
    import fsspec

    path = fsspec.open_local({url!r}{fsspec_kwargs})
    con = duckdb.connect(path, read_only=True{connect})
    con.sql('show all tables')
    """)


@code(
    format=DuckDBDatabase, engine=DuckDBEngine, label=OPEN_DATABASE, requires=_REQUIRES
)
def database_code(ctx: ItemContext, options: DuckDBOptions) -> str:
    """The code opening the database read only, and listing its tables; a
    remote file is downloaded once by fsspec, with
    ``fsspec_storage_options``."""
    connect = options.connect_code()
    if isinstance(ctx.location, LocalLocation):
        return _LOCAL_DATABASE_CODE.format(path=ctx.url_or_local_path, connect=connect)
    scheme = _scheme(ctx)
    storage = options.code_value("fsspec_storage_options")
    # fsspec's options of a chained URL's storage go by its protocol.
    fsspec_kwargs = (
        format_kwargs(**{scheme: storage}) if storage and scheme.isidentifier() else ""
    )
    return _REMOTE_DATABASE_CODE.format(
        url=f"simplecache::{ctx.location.url}",
        fsspec_kwargs=fsspec_kwargs,
        connect=connect,
    )


@view(
    format=DuckDBDatabase, engine=DuckDBEngine, requires=_REQUIRES, code=database_code
)
def database_view(ctx: ItemContext, options: DuckDBOptions, limits: ViewLimits) -> View:
    """The database's tables and views, opened read only, each queried when
    chosen; a ``TextView`` if it has none. A remote file larger than
    ``limits.max_whole_file_bytes``, and not copied yet, is downloaded once
    the user confirms."""
    cache = local_file_cache()

    def release(view: View | None = None) -> None:
        cache.release(ctx.location, delay=_COPY_KEPT)

    def open_database() -> View:
        path = cache.get(ctx)
        try:
            con = _connect(options, str(path), read_only=True)
        except BaseException:
            release()
            raise
        try:
            tables = con.sql(
                "select table_schema, table_name from information_schema.tables"
                " where table_catalog = current_database()"
                " order by table_schema, table_name"
            ).fetchall()
        except BaseException:
            con.close()
            release()
            raise
        if not tables:
            con.close()
            release()
            return TextView(text=f"{ctx.name} has no tables.")
        # A query rather than con.table, which parses no quotes in names
        # and finds no view by a qualified name.
        view = TableSetView(
            nodes=_table_nodes(tables),
            loader=lambda name: con.sql(f"select * from {name}"),
        )
        view.on_close(lambda view: con.close())
        view.on_close(release)
        return view

    remote = not isinstance(ctx.location, LocalLocation)
    size = ctx.size
    if (
        remote
        and cache.status(ctx) != "cached"
        and (size is None or size > limits.max_whole_file_bytes)
    ):
        size_text = f" ({format_size(size)})" if size else ""
        return ViewWithConfirmation(
            message=(
                f"DuckDB opens only local databases: {ctx.name}{size_text} "
                "is downloaded to the kernel's disk first."
            ),
            factory=open_database,
            button="Download",
        )
    return open_database()


# In the order tried.
DUCKDB_ACTIONS = register_actions(
    delta_view,
    delta_as_relation,
    parquet_view,
    parquet_as_relation,
    csv_view,
    csv_as_relation,
    json_lines_view,
    json_lines_as_relation,
    database_view,
    database_code,
)
