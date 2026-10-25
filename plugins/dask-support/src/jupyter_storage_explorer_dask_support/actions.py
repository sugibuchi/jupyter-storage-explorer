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

from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats.actions import (
    ActionOptions,
    code,
    register_actions,
    view,
)
from jupyter_storage_explorer.formats.base import ItemContext
from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.local_files import local_file_cache
from jupyter_storage_explorer.formats.packages import PyArrow, PythonPackage
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import Csv, JsonLines
from jupyter_storage_explorer.formats.views import (
    QueryView,
    View,
    ViewLimits,
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
    from collections.abc import Mapping, Sequence

    from fsspec.spec import AbstractFileSystem

AS_DATA_FRAME = "Load as DataFrame"

# How long a local copy no view uses is kept, in seconds, so that viewing the
# file again soon reuses it.
_COPY_KEPT = 600


# The engine's libraries: Dask, and pandas, which Dask's partitions are and
# the data browser collects them into. PyArrow, which dask.dataframe
# requires, is the core's (jupyter_storage_explorer.formats.packages).


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
    """The options of every Dask action.

    Attributes
    ----------
    storage_options : mapping or None, default None
        Dask's (fsspec's) ``storage_options`` in the code; those that look
        like credentials are left out. The data browser reads through the
        explorer's filesystem, with its own credentials.
    """

    storage_options: Mapping[str, Any] | None = secret_dict_field(
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
# block). LIBRARY_DEFAULT leaves one to Dask. The plugin's README has their
# tables: keep them in step.
_Default = LibraryDefault


@dataclass(frozen=True, kw_only=True)
class ParquetByDaskOptions(DaskOptions):
    """Dask's ``read_parquet`` arguments, besides ``storage_options``: unset
    ones are left to Dask, but in the data browser ``split_row_groups``
    (True for a file, unless ``blocksize`` is given). The plugin's README
    lists them."""

    columns: Sequence[str] | _Default | None = LIBRARY_DEFAULT
    filters: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    index: str | Sequence[str] | bool | _Default | None = LIBRARY_DEFAULT
    categories: Sequence[str] | Mapping[str, int] | _Default | None = LIBRARY_DEFAULT
    open_file_options: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default | None = LIBRARY_DEFAULT
    calculate_divisions: bool | _Default = LIBRARY_DEFAULT
    ignore_metadata_file: bool | _Default = LIBRARY_DEFAULT
    metadata_task_size: int | _Default | None = LIBRARY_DEFAULT
    split_row_groups: str | bool | int | _Default = LIBRARY_DEFAULT
    blocksize: str | int | _Default | None = LIBRARY_DEFAULT
    aggregate_files: bool | str | _Default | None = LIBRARY_DEFAULT
    parquet_file_extension: str | Sequence[str] | _Default | None = LIBRARY_DEFAULT
    dataset: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    read: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    arrow_to_pandas: Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class CsvByDaskOptions(DaskOptions):
    """Dask's ``read_csv`` arguments, and pandas' it passes on, besides
    ``storage_options``: unset ones are left to Dask and pandas, but ``sep``
    (detected from the file's beginning) and, in the data browser,
    ``blocksize`` (half of ``max_whole_file_bytes``). The plugin's README
    lists them."""

    # Dask's own.
    blocksize: str | int | _Default | None = LIBRARY_DEFAULT
    sample: int | _Default = LIBRARY_DEFAULT
    sample_rows: int | _Default = LIBRARY_DEFAULT
    enforce: bool | _Default = LIBRARY_DEFAULT
    assume_missing: bool | _Default = LIBRARY_DEFAULT
    include_path_column: bool | str | _Default = LIBRARY_DEFAULT
    # pandas' read_csv's.
    sep: str | _Default | None = LIBRARY_DEFAULT
    header: int | Sequence[int] | str | _Default | None = LIBRARY_DEFAULT
    names: Sequence[str] | _Default = LIBRARY_DEFAULT
    usecols: Sequence[int | str] | _Default | None = LIBRARY_DEFAULT
    dtype: Any = LIBRARY_DEFAULT
    engine: str | _Default | None = LIBRARY_DEFAULT
    true_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    false_values: Sequence[Any] | _Default | None = LIBRARY_DEFAULT
    skipinitialspace: bool | _Default = LIBRARY_DEFAULT
    skiprows: int | Sequence[int] | _Default | None = LIBRARY_DEFAULT
    skipfooter: int | _Default = LIBRARY_DEFAULT
    na_values: Any = LIBRARY_DEFAULT
    keep_default_na: bool | _Default = LIBRARY_DEFAULT
    na_filter: bool | _Default = LIBRARY_DEFAULT
    skip_blank_lines: bool | _Default = LIBRARY_DEFAULT
    parse_dates: bool | Sequence[int | str] | _Default | None = LIBRARY_DEFAULT
    date_format: str | Mapping[str, str] | _Default | None = LIBRARY_DEFAULT
    dayfirst: bool | _Default = LIBRARY_DEFAULT
    cache_dates: bool | _Default = LIBRARY_DEFAULT
    compression: str | Mapping[str, Any] | _Default | None = LIBRARY_DEFAULT
    thousands: str | _Default | None = LIBRARY_DEFAULT
    decimal: str | _Default = LIBRARY_DEFAULT
    lineterminator: str | _Default | None = LIBRARY_DEFAULT
    quotechar: str | _Default = LIBRARY_DEFAULT
    quoting: int | _Default = LIBRARY_DEFAULT
    doublequote: bool | _Default = LIBRARY_DEFAULT
    escapechar: str | _Default | None = LIBRARY_DEFAULT
    comment: str | _Default | None = LIBRARY_DEFAULT
    encoding: str | _Default | None = LIBRARY_DEFAULT
    encoding_errors: str | _Default | None = LIBRARY_DEFAULT
    on_bad_lines: str | _Default = LIBRARY_DEFAULT
    low_memory: bool | _Default = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT


@dataclass(frozen=True, kw_only=True)
class JsonLinesByDaskOptions(DaskOptions):
    """Dask's ``read_json`` arguments for JSON Lines (``lines=True``), and
    pandas' it passes on, besides ``storage_options``: unset ones are left to
    Dask and pandas, but in the data browser ``blocksize`` (half of
    ``max_whole_file_bytes``). The plugin's README lists them."""

    # Dask's own.
    blocksize: int | _Default | None = LIBRARY_DEFAULT
    sample: int | _Default = LIBRARY_DEFAULT
    encoding: str | _Default = LIBRARY_DEFAULT
    errors: str | _Default = LIBRARY_DEFAULT
    compression: str | _Default | None = LIBRARY_DEFAULT
    include_path_column: bool | str | _Default = LIBRARY_DEFAULT
    # pandas' read_json's.
    dtype: Any = LIBRARY_DEFAULT
    convert_axes: bool | _Default | None = LIBRARY_DEFAULT
    convert_dates: bool | Sequence[str] | _Default = LIBRARY_DEFAULT
    keep_default_dates: bool | _Default = LIBRARY_DEFAULT
    precise_float: bool | _Default = LIBRARY_DEFAULT
    date_unit: str | _Default | None = LIBRARY_DEFAULT
    dtype_backend: str | _Default = LIBRARY_DEFAULT


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
def parquet_view(
    fmt: Parquet, ctx: ItemContext, options: ParquetByDaskOptions, limits: ViewLimits
) -> View:
    """A DataFrame of the Parquet file, or of the folder's data files, which
    the data browser reads a partition at a time (the core's
    ``fetch_rows``). ``limits`` are not used: Dask reads only the partitions
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
    if isinstance(ctx.location, LocalLocation):
        return QueryView(data=read(ctx.url_or_local_path, **arguments))
    if (rebuilt := _rebuilt_url(ctx)) is not None:
        url, storage_options = rebuilt
        return QueryView(data=read(url, storage_options=storage_options, **arguments))
    cache = local_file_cache()

    def copied() -> View:
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
def json_lines_as_data_frame(
    fmt: JsonLines, ctx: ItemContext, options: JsonLinesByDaskOptions
) -> str:
    """The code reading the file into a Dask DataFrame."""
    return _dask_code(
        "read_json({url}, lines=True", ctx.url_or_local_path, _code_kwargs(options, {})
    )


@view(format=JsonLines, engine=DaskEngine, code=json_lines_as_data_frame)
def json_lines_view(
    fmt: JsonLines,
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
