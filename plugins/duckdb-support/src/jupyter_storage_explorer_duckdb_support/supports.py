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
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any, ClassVar

from fsspec.implementations.dirfs import DirFileSystem
from fsspec.spec import AbstractFileSystem

from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.base import DataFormat
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.local_files import local_file_cache
from jupyter_storage_explorer.formats.package import PythonPackage
from jupyter_storage_explorer.formats.packages import PyArrow
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import (
    LIBRARY_DEFAULT,
    FormatSupport,
    LibraryDefault,
    SupportOptions,
    format_arguments,
    format_kwargs,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.view import (
    Leaf,
    Node,
    QueryView,
    TableSetView,
    TextView,
    ViewWithChoice,
    ViewWithConfirmation,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.support import Task
    from jupyter_storage_explorer.formats.view import View, ViewLimits

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
class DuckDBOptions(SupportOptions):
    """The options of every DuckDB support: the connection, and how DuckDB
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


def reads_by_url(ctx: ItemContext, options: DuckDBOptions) -> bool:
    """Whether the views read the item by URL: a local file, or one of
    ``options.url_schemes``. Elsewhere they read it through the explorer's
    filesystem.

    Parameters
    ----------
    ctx : ItemContext
        The item.
    options : DuckDBOptions
        The support's options for it.

    Returns
    -------
    bool
    """
    if isinstance(ctx.location, LocalLocation):
        return True
    return _scheme(ctx) in {s.lower() for s in options.url_schemes}


def _code_reads_url(ctx: ItemContext, options: DuckDBOptions) -> bool:
    """Whether the code reads the item by URL: where the views do, and on
    the storages DuckDB's extensions reach. Elsewhere it registers fsspec's
    filesystem."""
    return reads_by_url(ctx, options) or _scheme(ctx) in _DUCKDB_SCHEMES


def _duckdb_url(ctx: ItemContext) -> str:
    """The item's URL as DuckDB reads it: a local file's plain path, and
    Azure's ``abfss://`` for ``abfs://``, which DuckDB does not take."""
    url = ctx.library_url
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


def _size_text(size: int) -> str:
    """``size`` bytes, as people read it, e.g. "586 MB"."""
    if size < 1024 * 1024:
        return f"{max(size // 1024, 1)} KB"
    return f"{size / (1024 * 1024):,.0f} MB"


def _quoted(*names: str) -> str:
    """A qualified name of DuckDB, each part quoted, e.g. ``"sales"."orders"``."""
    return ".".join('"' + name.replace('"', '""') + '"' for name in names)


class _DuckDBSupport(FormatSupport):
    """A format read with DuckDB, on a connection of each view's own, closed
    with it."""

    engine = DuckDBEngine
    # The data browser collects DuckDB's results into PyArrow tables
    # (narwhals' default for DuckDB).
    additional_requirements = (PyArrow(),)
    options_model = DuckDBOptions

    @staticmethod
    def _connect(
        options: DuckDBOptions, database: str = ":memory:", **kwargs: Any
    ) -> Any:
        return DuckDB().load().connect(database, **kwargs, **options.connect_kwargs())

    @staticmethod
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


class ParquetByDuckDB(_DuckDBSupport):
    """Parquet files and folders with DuckDB: lazily by URL where DuckDB reads
    the storage itself; elsewhere, as lazily, through the explorer's
    filesystem, where DuckDB can read through it."""

    format = Parquet
    options_model = ParquetByDuckDBOptions

    def supports(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: ParquetByDuckDBOptions,
        task: Task,
    ) -> bool:
        """Views by URL, or through the explorer's filesystem where DuckDB
        reads it (``modified``); code everywhere.

        Parameters
        ----------
        fmt : Parquet
            The format.
        ctx : ItemContext
            The file or folder.
        options : ParquetByDuckDBOptions
            Its options: ``url_schemes``.
        task : {"view", "recipe"}
            What the explorer asks.

        Returns
        -------
        bool
        """
        reached = (
            task != "view" or reads_by_url(ctx, options) or _readable_registered(ctx.fs)
        )
        return super().supports(fmt, ctx, options, task) and reached

    def data_url(self, fmt: Parquet, ctx: ItemContext, url: str) -> str:
        """The data files of the item at ``url``: a file's URL, or a glob of a
        folder's data files.

        Parameters
        ----------
        fmt : Parquet
            The format, with the folder's layout.
        ctx : ItemContext
            The file or folder.
        url : str
            Its URL as DuckDB reads it.

        Returns
        -------
        str
        """
        url = fmt.data_url(ctx, url)
        if ctx.is_dir and fmt.layout(ctx).files == "*":
            # Data files without an extension (Hive's): not "_SUCCESS" or
            # ".crc" checksums, which DuckDB would read.
            url = url.removesuffix("*") + "[!_.]*"
        return url

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: ParquetByDuckDBOptions,
        limits: ViewLimits,
    ) -> View:
        """A relation of the Parquet file, or of the folder's data files, with
        a folder's partition columns.

        Parameters
        ----------
        fmt : Parquet
            The format, with the folder's layout.
        ctx : ItemContext
            The file or folder.
        options : ParquetByDuckDBOptions
            The connection's options and ``read_parquet``'s arguments.
        limits : ViewLimits
            Not used: DuckDB reads only what the data browser asks.

        Returns
        -------
        QueryView
        """
        partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
        arguments = {"hive_partitioning": partitioned, **options.arguments()}

        def read(con: Any) -> Any:
            if reads_by_url(ctx, options):
                url = _duckdb_url(ctx)
            else:
                # The explorer's filesystem as it is, on this connection only:
                # DuckDB reads it before its own readers (e.g. httpfs' s3://),
                # and its own URL of the item, not the location's.
                con.register_filesystem(ctx.fs)
                url = ctx.fs.unstrip_protocol(ctx.path)
            return con.read_parquet(self.data_url(fmt, ctx, url), **arguments)

        return self._query_view(self._connect(options), read)

    relation_template = cleandoc("""
        import duckdb

        con = duckdb.connect({connect})
        rel = con.read_parquet({url}{kwargs})
        """)

    fsspec_template = cleandoc("""
        import duckdb
        import fsspec

        con = duckdb.connect({connect})
        fs, _ = fsspec.url_to_fs({url}{fsspec_kwargs})
        con.register_filesystem(fs)
        rel = con.read_parquet({url}{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: ParquetByDuckDBOptions
    ) -> dict[str, str]:
        """The code reading the file or folder into a relation.

        Parameters
        ----------
        fmt : Parquet
            The format, with the folder's layout.
        ctx : ItemContext
            The file or folder.
        options : ParquetByDuckDBOptions
            The connection's options and ``read_parquet``'s arguments.

        Returns
        -------
        dict of str to str
        """
        partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
        arguments = {"hive_partitioning": True} if partitioned else {}
        arguments.update(options.code_arguments())
        by_url = _code_reads_url(ctx, options)
        template = self.relation_template if by_url else self.fsspec_template
        url = _duckdb_url(ctx) if by_url else ctx.location.url
        code = template.format(
            connect=options.connect_code().removeprefix(", "),
            url=repr(self.data_url(fmt, ctx, url)),
            kwargs=format_arguments(arguments),
            fsspec_kwargs=options.fsspec_kwargs(),
        )
        return {AS_RELATION: code}


class _TextByDuckDB(_DuckDBSupport):
    """A text format of files (CSV, JSON Lines), which DuckDB reads whole for
    each filter, sort or count: by URL where DuckDB reads the storage itself;
    elsewhere from a copy on the kernel's disk, or the file's beginning in
    memory, as the user chooses for a large file."""

    # The reader's method of a connection, and the support's own arguments.
    reader: ClassVar[str] = ""
    defaults: ClassVar[Mapping[str, Any]] = {}

    def _read(self, con: Any, source: Any, options: SupportOptions) -> Any:
        arguments = {**self.defaults, **options.arguments()}
        return getattr(con, self.reader)(source, **arguments)

    def view(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        options: DuckDBOptions,
        limits: ViewLimits,
    ) -> View:
        """A relation of the file.

        Off the storages DuckDB reads itself, a file larger than
        ``limits.max_whole_file_bytes`` and not copied yet is read once the
        user chooses: copied to the kernel's disk whole, or its first bytes up
        to that size, cut after their last line, read into memory.

        Parameters
        ----------
        fmt : DataFormat
            The format.
        ctx : ItemContext
            The file.
        options : DuckDBOptions
            The connection's options and the reader's arguments.
        limits : ViewLimits
            ``max_whole_file_bytes``: the largest file copied without asking.

        Returns
        -------
        QueryView or ViewWithChoice
        """
        if reads_by_url(ctx, options):
            url = _duckdb_url(ctx)
            return self._query_view(
                self._connect(options), lambda con: self._read(con, url, options)
            )
        cache = local_file_cache()

        def copied() -> View:
            path = cache.get(ctx).as_posix()
            try:
                view = self._query_view(
                    self._connect(options), lambda con: self._read(con, path, options)
                )
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
            return self._query_view(
                self._connect(options),
                lambda con: self._read(con, io.BytesIO(data), options),
                more=cut,
            )

        size = ctx.size
        limit = limits.max_whole_file_bytes
        if cache.status(ctx) == "cached" or (size is not None and size <= limit):
            return copied()
        whole = f"The whole file ({_size_text(size)})" if size else "The whole file"
        return ViewWithChoice(
            message=(
                "DuckDB cannot read this storage itself, and reads the whole file "
                "for each query: the file is copied to the kernel's disk first, "
                "or its beginning read into memory."
            ),
            choices={f"Its first {_size_text(limit)}": limit, whole: None},
            factory=lambda size: copied() if size is None else first(size),
            style="button",
            with_cancel=True,
        )

    relation_template = cleandoc("""
        import duckdb

        con = duckdb.connect({connect})
        rel = con.{reader}({url}{kwargs})
        """)

    fsspec_template = cleandoc("""
        import duckdb
        import fsspec

        con = duckdb.connect({connect})
        fs, _ = fsspec.url_to_fs({url}{fsspec_kwargs})
        con.register_filesystem(fs)
        rel = con.{reader}({url}{kwargs})
        """)

    def recipe(
        self, fmt: DataFormat, ctx: ItemContext, options: DuckDBOptions
    ) -> dict[str, str]:
        """The code reading the file into a relation.

        Parameters
        ----------
        fmt : DataFormat
            The format.
        ctx : ItemContext
            The file.
        options : DuckDBOptions
            The connection's options and the reader's arguments.

        Returns
        -------
        dict of str to str
        """
        by_url = _code_reads_url(ctx, options)
        template = self.relation_template if by_url else self.fsspec_template
        code = template.format(
            connect=options.connect_code().removeprefix(", "),
            reader=self.reader,
            url=repr(_duckdb_url(ctx) if by_url else ctx.location.url),
            kwargs=format_arguments({**self.defaults, **options.code_arguments()}),
            fsspec_kwargs=options.fsspec_kwargs(),
        )
        return {AS_RELATION: code}


class CsvByDuckDB(_TextByDuckDB):
    """CSV files with DuckDB, whose sniffer detects the dialect: the data
    browser, and code."""

    format = Csv
    options_model = CsvByDuckDBOptions
    reader = "read_csv"


class JsonLinesByDuckDB(_TextByDuckDB):
    """JSON Lines files with DuckDB: the data browser, and code."""

    format = JsonLines
    options_model = JsonLinesByDuckDBOptions
    reader = "read_json"
    # Rather than DuckDB's detection, which also takes a JSON array.
    defaults: ClassVar[Mapping[str, Any]] = {"format": "newline_delimited"}


class DeltaLakeByDuckDB(_DuckDBSupport):
    """Delta Lake tables with DuckDB's delta extension, by URL only: locally,
    and on the storages DuckDB reads itself (``url_schemes``; in the code, those
    its extensions reach).

    DuckDB installs and loads the extension at the first query, unless its
    settings forbid it.
    """

    format = DeltaLake
    options_model = DeltaLakeByDuckDBOptions

    def supports(
        self,
        fmt: DeltaLake,
        ctx: ItemContext,
        options: DeltaLakeByDuckDBOptions,
        task: Task,
    ) -> bool:
        """Views where DuckDB reads the storage itself, code also where its
        extensions do: ``delta_scan`` reads no registered filesystem.

        Parameters
        ----------
        fmt : DeltaLake
            The format.
        ctx : ItemContext
            The table's folder.
        options : DeltaLakeByDuckDBOptions
            Its options: ``url_schemes``.
        task : {"view", "recipe"}
            What the explorer asks.

        Returns
        -------
        bool
        """
        reached = (
            reads_by_url(ctx, options)
            if task == "view"
            else _code_reads_url(ctx, options)
        )
        return super().supports(fmt, ctx, options, task) and reached

    @staticmethod
    def _query(ctx: ItemContext, options: DeltaLakeByDuckDBOptions) -> str:
        parameters = "".join(
            f", {name} := {_sql_literal(value)}"
            for name, value in options.arguments().items()
        )
        return f"select * from delta_scan({_sql_literal(_duckdb_url(ctx))}{parameters})"

    def view(
        self,
        fmt: DeltaLake,
        ctx: ItemContext,
        options: DeltaLakeByDuckDBOptions,
        limits: ViewLimits,
    ) -> View:
        """A relation of the table, by ``delta_scan``.

        Parameters
        ----------
        fmt : DeltaLake
            The format.
        ctx : ItemContext
            The table's folder.
        options : DeltaLakeByDuckDBOptions
            The connection's options and ``delta_scan``'s parameters.
        limits : ViewLimits
            Not used: DuckDB reads only what the data browser asks.

        Returns
        -------
        QueryView
        """
        query = self._query(ctx, options)
        return self._query_view(self._connect(options), lambda con: con.sql(query))

    relation_template = cleandoc("""
        import duckdb

        con = duckdb.connect({connect})
        rel = con.sql({query})
        """)

    def recipe(
        self, fmt: DeltaLake, ctx: ItemContext, options: DeltaLakeByDuckDBOptions
    ) -> dict[str, str]:
        """The code reading the table into a relation.

        Parameters
        ----------
        fmt : DeltaLake
            The format.
        ctx : ItemContext
            The table's folder.
        options : DeltaLakeByDuckDBOptions
            The connection's options and ``delta_scan``'s parameters.

        Returns
        -------
        dict of str to str
        """
        code = self.relation_template.format(
            connect=options.connect_code().removeprefix(", "),
            query=repr(self._query(ctx, options)),
        )
        return {AS_RELATION: code}


def _table_nodes(tables: Sequence[tuple[str, str]]) -> list[Node]:
    """A database's tables and views, by schema; without the schema when
    there is only one."""
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
        )
        for schema in schemas
    ]


class DuckDBDatabaseByDuckDB(_DuckDBSupport):
    """DuckDB's database files: their tables and views in the data browser,
    and code opening them.

    DuckDB opens only local files, also with a filesystem registered: other
    storages' are copied to the kernel's disk first, after asking for a large
    one.
    """

    format = DuckDBDatabase

    def view(
        self,
        fmt: DuckDBDatabase,
        ctx: ItemContext,
        options: DuckDBOptions,
        limits: ViewLimits,
    ) -> View:
        """The database's tables and views, opened read only, each queried
        when chosen.

        Parameters
        ----------
        fmt : DuckDBDatabase
            The format.
        ctx : ItemContext
            The database file.
        options : DuckDBOptions
            The connection's options.
        limits : ViewLimits
            ``max_whole_file_bytes``: the largest file copied without asking.

        Returns
        -------
        TableSetView, TextView or ViewWithConfirmation
            A ``TextView`` if the database has no table.
        """
        cache = local_file_cache()

        def release(view: View | None = None) -> None:
            cache.release(ctx.location, delay=_COPY_KEPT)

        def open_database() -> View:
            path = cache.get(ctx)
            try:
                con = self._connect(options, str(path), read_only=True)
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
            size_text = f" ({_size_text(size)})" if size else ""
            return ViewWithConfirmation(
                message=(
                    f"DuckDB opens only local databases: {ctx.name}{size_text} "
                    "is downloaded to the kernel's disk first."
                ),
                factory=open_database,
                button="Download",
            )
        return open_database()

    local_template = cleandoc("""
        import duckdb

        con = duckdb.connect({path}, read_only=True{connect})
        con.sql('show all tables')
        """)

    # fsspec downloads the file once: DuckDB opens only local databases.
    download_template = cleandoc("""
        import duckdb
        import fsspec

        path = fsspec.open_local({url}{fsspec_kwargs})
        con = duckdb.connect(path, read_only=True{connect})
        con.sql('show all tables')
        """)

    def recipe(
        self, fmt: DuckDBDatabase, ctx: ItemContext, options: DuckDBOptions
    ) -> dict[str, str]:
        """The code opening the database read only, and listing its tables.

        Parameters
        ----------
        fmt : DuckDBDatabase
            The format.
        ctx : ItemContext
            The database file.
        options : DuckDBOptions
            The connection's options; ``fsspec_storage_options`` for a remote
            file's download.

        Returns
        -------
        dict of str to str
        """
        if isinstance(ctx.location, LocalLocation):
            code = self.local_template.format(
                path=repr(ctx.library_url), connect=options.connect_code()
            )
            return {OPEN_DATABASE: code}
        scheme = _scheme(ctx)
        storage = options.code_value("fsspec_storage_options")
        # fsspec's options of a chained URL's storage go by its protocol.
        fsspec_kwargs = (
            format_kwargs(**{scheme: storage})
            if storage and scheme.isidentifier()
            else ""
        )
        code = self.download_template.format(
            url=repr(f"simplecache::{ctx.location.url}"),
            fsspec_kwargs=fsspec_kwargs,
            connect=options.connect_code(),
        )
        return {OPEN_DATABASE: code}
