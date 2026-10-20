"""Formats handled with polars: the data browser and load code."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    library_url,
    snippet_options,
)
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.packages import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.packages import Fastexcel, Fsspec, Polars
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines
from jupyter_storage_explorer.formats.view import QueryView

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits

AS_LAZY_FRAME = "Load as LazyFrame"
AS_DATA_FRAME = "Load as DataFrame"


class _PolarsByUrl(FormatSupport):
    """A format polars reads by URL, with the storage options of its readers."""

    engine = Polars

    def __init__(
        self,
        *,
        storage_options: Mapping[str, Any] | None = None,
        credential_provider: Any = "auto",
    ) -> None:
        """``storage_options`` and ``credential_provider``: polars' arguments
        of these names, for the data browser and the code. In the code,
        storage options that look like credentials are left out, as is the
        credential provider."""
        self.storage_options = storage_options
        self.credential_provider = credential_provider

    def storage(self) -> dict[str, Any]:
        """polars' keyword arguments reaching the storage."""
        return {
            "storage_options": self.storage_options,
            "credential_provider": self.credential_provider,
        }

    def code_storage_options(self) -> Mapping[str, Any] | None:
        """The storage options fit to show in code (see ``snippet_options``), or None."""
        return snippet_options(self.storage_options) or None


class CsvByPolars(_PolarsByUrl):
    format = Csv
    capabilities = ("view", "recipe")

    def view(self, fmt: Csv, ctx: ItemContext, *, limits: ViewLimits) -> View:
        pl = Polars().load()
        url = library_url(ctx.location)
        # The first lines, read by polars too, so any URL it reads works.
        lines = pl.scan_lines(url, **self.storage()).head(20).collect()["line"]
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        data = pl.scan_csv(
            url,
            separator=fmt.separator(url, "\n".join(lines)),
            truncate_ragged_lines=True,
            try_parse_dates=True,
            **self.storage(),
        )
        return QueryView(data=data)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_csv({url}{kwargs})
        """)

    def recipe(self, fmt: Csv, ctx: ItemContext) -> dict[str, str]:
        kwargs = format_kwargs(
            separator=fmt.code_separator(ctx.fs, ctx.path),
            storage_options=self.code_storage_options(),
        )
        url = repr(library_url(ctx.location))
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs)}


class JsonLinesByPolars(_PolarsByUrl):
    format = JsonLines
    capabilities = ("view", "recipe")

    def view(self, fmt: JsonLines, ctx: ItemContext, *, limits: ViewLimits) -> View:
        data = Polars().load().scan_ndjson(library_url(ctx.location), **self.storage())
        return QueryView(data=data)

    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_ndjson({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_ndjson({url}{kwargs})
        """)

    def recipe(self, fmt: JsonLines, ctx: ItemContext) -> dict[str, str]:
        url = repr(library_url(ctx.location))
        kwargs = format_kwargs(storage_options=self.code_storage_options())
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs),
        }


class JsonByPolars(FormatSupport):
    """Load code only: JSON is viewed as a tree (``JsonByPython``)."""

    format = Json
    engine = Polars
    capabilities = ("recipe",)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_json({url})
        """)

    def recipe(self, fmt: Json, ctx: ItemContext) -> dict[str, str]:
        # polars' read_json takes no storage options.
        url = repr(library_url(ctx.location))
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url)}


class ExcelByPolars(FormatSupport):
    format = Excel
    engine = Polars
    # fastexcel reads workbooks for polars; the code reads the bytes with fsspec.
    additional_requirements = (Fastexcel, Fsspec)
    capabilities = ("view", "recipe")

    def __init__(
        self, *, fsspec_storage_options: Mapping[str, Any] | None = None
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the code, which reads the bytes with it; ones that look like
        credentials are left out."""
        self.fsspec_storage_options = fsspec_storage_options

    def view(self, fmt: Excel, ctx: ItemContext, *, limits: ViewLimits) -> View:
        # Excel cannot be read lazily: the first sheet is read whole, through
        # the explorer's filesystem, and queried in memory.
        size = ctx.info.get("size")
        if size is not None and size > limits.max_whole_file_bytes:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to view (over {limit} MB)")
        Fastexcel().load()  # polars reads workbooks with fastexcel
        return QueryView(data=Polars().load().read_excel(ctx.fs.cat_file(ctx.path)))

    # polars reads the bytes, fetched with fsspec so any storage works.
    data_frame_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            df = pl.read_excel(f.read())
        """)

    def recipe(self, fmt: Excel, ctx: ItemContext) -> dict[str, str]:
        kwargs = format_kwargs(**snippet_options(self.fsspec_storage_options))
        url = repr(library_url(ctx.location))
        return {AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs)}


class ParquetByPolars(_PolarsByUrl):
    format = Parquet
    capabilities = ("view", "recipe")

    def view(self, fmt: Parquet, ctx: ItemContext, *, limits: ViewLimits) -> View:
        """A LazyFrame over a Parquet file, or over a directory's data files.

        For a directory, its data files as ``matches`` found them (see
        ``Parquet.data_url``); partition folders give columns ("year=2026": a
        column "year"). Names starting with "." or "_" are skipped, as Spark
        writes "_SUCCESS" and ".crc" checksums next to the data.
        """
        layout = fmt.layout(ctx) if ctx.is_dir else None
        data = (
            Polars()
            .load()
            .scan_parquet(
                fmt.data_url(ctx),
                hive_partitioning=layout is not None and bool(layout.keys),
                hidden_file_prefix=[".", "_"],
                **self.storage(),
            )
        )
        return QueryView(data=data)

    # A LazyFrame, so only the needed rows and columns are read.
    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_parquet({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_parquet({url}{kwargs})
        """)

    # read_parquet takes no hidden_file_prefix: scanned, then read.
    data_frame_scanned_template = cleandoc("""
        import polars as pl

        df = pl.scan_parquet({url}{kwargs}).collect()
        """)

    def recipe(self, fmt: Parquet, ctx: ItemContext) -> dict[str, str]:
        layout = fmt.layout(ctx) if ctx.is_dir else None
        # "*" also matches Spark's "_SUCCESS" and checksums.
        hidden = layout is not None and layout.files == "*"
        url = repr(fmt.data_url(ctx))
        kwargs = format_kwargs(
            hive_partitioning=True if layout and layout.keys else None,
            hidden_file_prefix=[".", "_"] if hidden else None,
            storage_options=self.code_storage_options(),
        )
        data_frame = (
            self.data_frame_scanned_template if hidden else self.data_frame_template
        )
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: data_frame.format(url=url, kwargs=kwargs),
        }


class DeltaLakeByPolars(_PolarsByUrl):
    format = DeltaLake
    # polars reads the table with deltalake (delta-rs), which reads cloud
    # storage itself, by default with credentials from the environment.
    additional_requirements = (DeltaLakePackage,)
    capabilities = ("view", "recipe")

    def __init__(
        self,
        *,
        storage_options: Mapping[str, Any] | None = None,
        credential_provider: Any = "auto",
        delta_table_options: Mapping[str, Any] | None = None,
        use_pyarrow: bool = False,
        pyarrow_options: Mapping[str, Any] | None = None,
    ) -> None:
        """Options of polars' ``scan_delta``, for the data browser and the
        code: ``storage_options`` and ``credential_provider``, as for the
        other formats polars reads, and ``delta_table_options``,
        ``use_pyarrow`` and ``pyarrow_options``.

        ``storage_options`` are delta-rs' (object_store's), not fsspec's;
        without them, credentials come from the environment. In the code,
        ones that look like credentials are left out, as is the credential
        provider.
        """
        super().__init__(
            storage_options=storage_options, credential_provider=credential_provider
        )
        self.delta_table_options = delta_table_options
        self.use_pyarrow = use_pyarrow
        self.pyarrow_options = pyarrow_options

    def view(self, fmt: DeltaLake, ctx: ItemContext, *, limits: ViewLimits) -> View:
        data = (
            Polars()
            .load()
            .scan_delta(
                library_url(ctx.location),
                **self.storage(),
                delta_table_options=self.delta_table_options,
                use_pyarrow=self.use_pyarrow,
                pyarrow_options=self.pyarrow_options,
            )
        )
        return QueryView(data=data)

    lazy_frame_template = cleandoc("""
        import polars as pl

        df = pl.scan_delta({url}{kwargs})
        """)

    data_frame_template = cleandoc("""
        import polars as pl

        df = pl.read_delta({url}{kwargs})
        """)

    def recipe(self, fmt: DeltaLake, ctx: ItemContext) -> dict[str, str]:
        url = repr(library_url(ctx.location))
        # Only the arguments that differ from scan_delta's (read_delta's) defaults.
        kwargs = format_kwargs(
            storage_options=self.code_storage_options(),
            delta_table_options=self.delta_table_options,
            use_pyarrow=True if self.use_pyarrow else None,
            pyarrow_options=self.pyarrow_options,
        )
        return {
            AS_LAZY_FRAME: self.lazy_frame_template.format(url=url, kwargs=kwargs),
            AS_DATA_FRAME: self.data_frame_template.format(url=url, kwargs=kwargs),
        }
