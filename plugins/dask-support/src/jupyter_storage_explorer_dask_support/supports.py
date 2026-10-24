"""Formats handled with Dask (``dask.dataframe``): the data browser and load
code.

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
  only. A folder's partitions are its files.
- CSV and JSON Lines: their readers take only a URL and fsspec's
  ``storage_options``. Given the explorer's, fsspec gives back the explorer's
  own instance, from its cache, where it can rebuild it so; elsewhere the
  file is copied to the kernel's disk first, asking for a large one. Making
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
from typing import TYPE_CHECKING, Any, ClassVar

import fsspec
from fsspec.core import split_protocol
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer.filesystems.locations import LocalLocation
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
from jupyter_storage_explorer.formats.view import QueryView, ViewWithConfirmation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from fsspec.spec import AbstractFileSystem

    from jupyter_storage_explorer.formats.base import DataFormat, ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits

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


def _dd() -> Any:
    """``dask.dataframe``."""
    return Dask().load("dataframe")


@dataclass(frozen=True, kw_only=True)
class DaskOptions(SupportOptions):
    """The options of every Dask support.

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
    (True for a file) and ``parquet_file_extension`` (None for a folder of
    files named without an extension, as Hive's). The plugin's README lists
    them."""

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
    """The URL and ``storage_options`` by which fsspec gives back the
    explorer's filesystem, from its cache, for readers taking only a URL;
    None where it cannot rebuild the instance so, e.g. one made with
    arguments by position or not registered for its protocol. Reads
    nothing."""
    fs, path = _unwrapped(ctx.fs, ctx.path)
    url = fs.unstrip_protocol(path)
    protocol = split_protocol(url)[0]
    try:
        rebuilt = fsspec.filesystem(protocol, **fs.storage_options)
    except Exception:
        return None
    return (url, dict(fs.storage_options)) if rebuilt is fs else None


def _size_text(size: int) -> str:
    """``size`` bytes, as people read it, e.g. "586 MB"."""
    if size < 1024 * 1024:
        return f"{max(size // 1024, 1)} KB"
    return f"{size / (1024 * 1024):,.0f} MB"


def _code_kwargs(options: DaskOptions, defaults: Mapping[str, Any]) -> str:
    """The code's keyword arguments: the support's ``defaults``, then the
    options' arguments given, then ``storage_options``."""
    arguments = {**defaults, **options.code_arguments()}
    return format_arguments(arguments) + format_kwargs(
        storage_options=options.code_value("storage_options")
    )


class _DaskSupport(FormatSupport):
    """A format read with Dask: lazy data, which the data browser reads a
    partition at a time (the core's ``fetch_rows``)."""

    engine = DaskEngine
    options_model = DaskOptions

    @staticmethod
    def _query_view(data: Any) -> QueryView:
        return QueryView(data=data)


class ParquetByDask(_DaskSupport):
    """Parquet files and folders with Dask, through the explorer's
    filesystem on every storage: a file's row groups are its partitions, a
    folder's files, with a partitioned folder's columns."""

    format = Parquet
    options_model = ParquetByDaskOptions

    @staticmethod
    def _hive_files(fmt: Parquet, ctx: ItemContext) -> bool:
        """Whether the folder's data files are named without an extension, as
        Hive's, which Dask skips by default."""
        return ctx.is_dir and fmt.layout(ctx).files == "*"

    def view(
        self,
        fmt: Parquet,
        ctx: ItemContext,
        options: ParquetByDaskOptions,
        limits: ViewLimits,
    ) -> View:
        """A DataFrame of the Parquet file, or of the folder's data files.

        Parameters
        ----------
        fmt : Parquet
            The format, with the folder's layout.
        ctx : ItemContext
            The file or folder.
        options : ParquetByDaskOptions
            ``read_parquet``'s arguments.
        limits : ViewLimits
            Not used: Dask reads only the partitions the data browser needs.

        Returns
        -------
        QueryView
        """
        defaults: dict[str, Any] = {}
        if not ctx.is_dir:
            defaults["split_row_groups"] = True
        elif self._hive_files(fmt, ctx):
            defaults["parquet_file_extension"] = None
        fs, path = _unwrapped(ctx.fs, ctx.path)
        data = _dd().read_parquet(
            path, filesystem=fs, **{**defaults, **options.arguments()}
        )
        return self._query_view(data)

    data_frame_template = cleandoc("""
        import dask.dataframe as dd

        df = dd.read_parquet({url}{kwargs})
        """)

    def recipe(
        self, fmt: Parquet, ctx: ItemContext, options: ParquetByDaskOptions
    ) -> dict[str, str]:
        """The code reading the file or folder into a Dask DataFrame.

        Parameters
        ----------
        fmt : Parquet
            The format, with the folder's layout.
        ctx : ItemContext
            The file or folder.
        options : ParquetByDaskOptions
            ``read_parquet``'s arguments and ``storage_options``.

        Returns
        -------
        dict of str to str
        """
        defaults = (
            {"parquet_file_extension": None} if self._hive_files(fmt, ctx) else {}
        )
        code = self.data_frame_template.format(
            url=repr(ctx.library_url), kwargs=_code_kwargs(options, defaults)
        )
        return {AS_DATA_FRAME: code}


class _TextByDask(_DaskSupport):
    """A text format of files (CSV, JSON Lines), read in blocks: by URL with
    the explorer's ``storage_options`` where fsspec gives back the explorer's
    filesystem so, else from a copy on the kernel's disk."""

    # The reader of dask.dataframe.
    reader: ClassVar[str] = ""

    def _defaults(
        self, fmt: DataFormat, ctx: ItemContext, options: SupportOptions
    ) -> dict[str, Any]:
        """The support's own arguments of the data browser's reader, before
        the options'."""
        return {}

    def view(
        self,
        fmt: DataFormat,
        ctx: ItemContext,
        options: DaskOptions,
        limits: ViewLimits,
    ) -> View:
        """A DataFrame of the file, in blocks of at most
        ``limits.max_whole_file_bytes`` bytes, unless ``blocksize`` says
        otherwise.

        Where fsspec cannot give back the explorer's filesystem by URL, the
        file is copied to the kernel's disk first: at once up to
        ``limits.max_whole_file_bytes``, after asking for a larger one.

        Parameters
        ----------
        fmt : DataFormat
            The format.
        ctx : ItemContext
            The file.
        options : DaskOptions
            The reader's arguments.
        limits : ViewLimits
            ``max_whole_file_bytes``: the largest block, and the largest file
            copied without asking.

        Returns
        -------
        QueryView or ViewWithConfirmation
        """
        arguments = {
            # Dask's blocks are one to two times the size asked for.
            "blocksize": max(1, limits.max_whole_file_bytes // 2),
            **self._defaults(fmt, ctx, options),
            **options.arguments(),
        }
        reader = getattr(_dd(), self.reader)
        if isinstance(ctx.location, LocalLocation):
            return self._query_view(reader(ctx.library_url, **arguments))
        if (rebuilt := _rebuilt_url(ctx)) is not None:
            url, storage_options = rebuilt
            return self._query_view(
                reader(url, storage_options=storage_options, **arguments)
            )
        cache = local_file_cache()

        def copied() -> View:
            path = cache.get(ctx).as_posix()
            try:
                view = self._query_view(reader(path, **arguments))
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
        size_text = f" ({_size_text(size)})" if size else ""
        return ViewWithConfirmation(
            message=(
                f"Dask cannot reach this storage by URL: {ctx.name}{size_text} is "
                "copied to the kernel's disk first."
            ),
            factory=copied,
            button="Copy",
        )

    data_frame_template: ClassVar[str] = ""

    def _code_defaults(self, fmt: DataFormat, ctx: ItemContext) -> dict[str, Any]:
        """The support's own arguments of the code's reader, before the
        options'."""
        return {}

    def recipe(
        self, fmt: DataFormat, ctx: ItemContext, options: DaskOptions
    ) -> dict[str, str]:
        """The code reading the file into a Dask DataFrame.

        Parameters
        ----------
        fmt : DataFormat
            The format.
        ctx : ItemContext
            The file.
        options : DaskOptions
            The reader's arguments and ``storage_options``.

        Returns
        -------
        dict of str to str
        """
        kwargs = _code_kwargs(options, self._code_defaults(fmt, ctx))
        code = self.data_frame_template.format(url=repr(ctx.library_url), kwargs=kwargs)
        return {AS_DATA_FRAME: code}


class CsvByDask(_TextByDask):
    """CSV files with Dask, the separator detected: the data browser, and
    code."""

    format = Csv
    options_model = CsvByDaskOptions
    reader = "read_csv"

    def _defaults(
        self, fmt: Csv, ctx: ItemContext, options: CsvByDaskOptions
    ) -> dict[str, Any]:
        if options.sep is not LIBRARY_DEFAULT:
            return {}
        return {"sep": fmt.separator(ctx.name, ctx.head_text(64 * 1024)[0])}

    data_frame_template = cleandoc("""
        import dask.dataframe as dd

        df = dd.read_csv({url}{kwargs})
        """)

    def _code_defaults(self, fmt: Csv, ctx: ItemContext) -> dict[str, Any]:
        sep = fmt.code_separator(ctx)
        return {"sep": sep} if sep is not None else {}


class JsonLinesByDask(_TextByDask):
    """JSON Lines files with Dask: the data browser, and code."""

    format = JsonLines
    options_model = JsonLinesByDaskOptions
    reader = "read_json"

    def _defaults(
        self, fmt: JsonLines, ctx: ItemContext, options: JsonLinesByDaskOptions
    ) -> dict[str, Any]:
        return {"lines": True}

    data_frame_template = cleandoc("""
        import dask.dataframe as dd

        df = dd.read_json({url}, lines=True{kwargs})
        """)
