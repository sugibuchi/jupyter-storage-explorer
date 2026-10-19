"""Formats handled with polars: previews, the data browser and load code."""

from __future__ import annotations

import io
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import format_kwargs, snippet_options
from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.frames import polars_table, rows_note, with_sheets
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.requirements import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.requirements import Fastexcel, Fsspec, Polars
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import Target
    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits


class _PolarsByUrl(FormatSupport):
    """A format polars reads by URL, with the storage options of its readers."""

    use = Polars

    def __init__(
        self,
        *,
        storage_options: Mapping[str, Any] | None = None,
        credential_provider: Any = "auto",
    ) -> None:
        """``storage_options`` and ``credential_provider``: polars' arguments
        of these names, for the data browser, previews read by URL and the
        code. In the code, storage options that look like credentials are
        left out, as is the credential provider."""
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
    capabilities = ("preview", "query", "recipe")

    def preview(self, fmt: Csv, target: Target, limits: PreviewLimits) -> Preview:
        pl = Polars().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pl.read_csv(
            io.BytesIO(text.encode()),
            separator=fmt.separator(target.name, text),
            n_rows=limits.max_rows,
            truncate_ragged_lines=True,
        )
        more = truncated or df.height == limits.max_rows
        return polars_table(df, note=rows_note(df.height, more))

    def query(self, fmt: Csv, url: str, is_dir: bool) -> Any:
        pl = Polars().load()
        # The first lines, read by polars too, so any URL it reads works.
        lines = pl.scan_lines(url, **self.storage()).head(20).collect()["line"]
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        return pl.scan_csv(
            url,
            separator=fmt.separator(url, "\n".join(lines)),
            truncate_ragged_lines=True,
            try_parse_dates=True,
            **self.storage(),
        )

    recipe_template = cleandoc("""
        import polars as pl

        df = pl.read_csv({url}{kwargs})
        """)

    def recipe(self, fmt: Csv, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                separator=fmt.code_separator(target),
                storage_options=self.code_storage_options(),
            ),
        )


class JsonLinesByPolars(_PolarsByUrl):
    format = JsonLines
    capabilities = ("preview", "query", "recipe")

    def preview(self, fmt: JsonLines, target: Target, limits: PreviewLimits) -> Preview:
        pl = Polars().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pl.read_ndjson(io.BytesIO(text.encode()), n_rows=limits.max_rows)
        more = truncated or df.height == limits.max_rows
        return polars_table(df, note=rows_note(df.height, more, "records"))

    def query(self, fmt: JsonLines, url: str, is_dir: bool) -> Any:
        return Polars().load().scan_ndjson(url, **self.storage())

    recipe_template = cleandoc("""
        import polars as pl

        df = pl.scan_ndjson({url}{kwargs})
        """)

    def recipe(self, fmt: JsonLines, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(storage_options=self.code_storage_options()),
        )


class JsonByPolars(FormatSupport):
    """Load code only: JSON is previewed as a tree (``JsonByPython``)."""

    format = Json
    use = Polars
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        import polars as pl

        df = pl.read_json({url})
        """)

    def recipe(self, fmt: Json, target: Target) -> str:
        # polars' read_json takes no storage options.
        return self.recipe_template.format(url=repr(target.url))


class ExcelByPolars(FormatSupport):
    format = Excel
    use = Polars
    # fastexcel reads workbooks for polars; the code reads the bytes with fsspec.
    additional_requirements = (Fastexcel, Fsspec)
    capabilities = ("preview", "query", "recipe")

    def __init__(
        self, *, fsspec_storage_options: Mapping[str, Any] | None = None
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the code, which reads the bytes with it; ones that look like
        credentials are left out."""
        self.fsspec_storage_options = fsspec_storage_options

    def preview(self, fmt: Excel, target: Target, limits: PreviewLimits) -> Preview:
        Polars().load()  # fastexcel's to_polars() needs polars
        fastexcel = Fastexcel().load()
        reader = fastexcel.read_excel(target.read_whole(limits))
        sheet = reader.load_sheet(0, n_rows=limits.max_rows)
        df = sheet.to_polars()
        note = rows_note(
            df.height, sheet.total_height > df.height, total=sheet.total_height
        )
        note = with_sheets(note, reader.sheet_names)
        return polars_table(df, title=sheet.name, note=note)

    def query(self, fmt: Excel, url: str, is_dir: bool) -> Any:
        # Excel cannot be read lazily: the first sheet is read whole and
        # queried in memory.
        return Polars().load().read_excel(url).lazy()

    # polars reads the bytes, fetched with fsspec so any storage works.
    recipe_template = cleandoc("""
        import fsspec
        import polars as pl

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            df = pl.read_excel(f.read())
        """)

    def recipe(self, fmt: Excel, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(**snippet_options(self.fsspec_storage_options)),
        )


class ParquetByPolars(_PolarsByUrl):
    format = Parquet
    capabilities = ("preview", "query", "recipe")

    def preview(self, fmt: Parquet, target: Target, limits: PreviewLimits) -> Preview:
        pl = Polars().load()
        lf = self.query(fmt, target.url, target.is_dir)
        df = lf.head(limits.max_rows).collect()
        if target.is_dir:
            note = rows_note(df.height, df.height == limits.max_rows)
        else:
            # Counting rows only reads the file's metadata.
            total = lf.select(pl.len()).collect().item()
            note = rows_note(df.height, df.height < total, total=total)
        return polars_table(df, note=note)

    def query(self, fmt: Parquet, url: str, is_dir: bool) -> Any:
        """A LazyFrame over a Parquet file, or over a directory's data files.

        For a directory, its data files as ``matches`` found them (see
        ``Parquet.data_url``); partition folders give columns ("year=2026": a
        column "year"). Names starting with "." or "_" are skipped, as Spark
        writes "_SUCCESS" and ".crc" checksums next to the data.
        """
        layout = fmt.layout(url) if is_dir else None
        return (
            Polars()
            .load()
            .scan_parquet(
                layout.glob(url) if layout is not None else url,
                hive_partitioning=layout is not None and bool(layout.keys),
                hidden_file_prefix=[".", "_"],
                **self.storage(),
            )
        )

    # A LazyFrame, so only the needed rows and columns are read.
    recipe_template = cleandoc("""
        import polars as pl

        df = pl.scan_parquet({url}{kwargs})
        """)

    def recipe(self, fmt: Parquet, target: Target) -> str:
        layout = fmt.target_layout(target) if target.is_dir else None
        return self.recipe_template.format(
            url=repr(fmt.data_url(target.url, target.is_dir)),
            kwargs=format_kwargs(
                hive_partitioning=True if layout and layout.keys else None,
                # "*" also matches Spark's "_SUCCESS" and checksums.
                hidden_file_prefix=[".", "_"]
                if layout and layout.files == "*"
                else None,
                storage_options=self.code_storage_options(),
            ),
        )


class DeltaLakeByPolars(_PolarsByUrl):
    format = DeltaLake
    # polars reads the table with deltalake (delta-rs), which reads cloud
    # storage itself, by default with credentials from the environment.
    additional_requirements = (DeltaLakePackage,)
    capabilities = ("preview", "query", "recipe")

    def __init__(
        self,
        *,
        storage_options: Mapping[str, Any] | None = None,
        credential_provider: Any = "auto",
        delta_table_options: Mapping[str, Any] | None = None,
        use_pyarrow: bool = False,
        pyarrow_options: Mapping[str, Any] | None = None,
    ) -> None:
        """Options of polars' ``scan_delta``, for the preview, the data browser
        and the code: ``storage_options`` and ``credential_provider``, as for
        the other formats polars reads, and ``delta_table_options``,
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

    def preview(self, fmt: DeltaLake, target: Target, limits: PreviewLimits) -> Preview:
        df = self.query(fmt, target.url, target.is_dir).head(limits.max_rows).collect()
        return polars_table(df, note=rows_note(df.height, df.height == limits.max_rows))

    def query(self, fmt: DeltaLake, url: str, is_dir: bool) -> Any:
        return (
            Polars()
            .load()
            .scan_delta(
                url,
                **self.storage(),
                delta_table_options=self.delta_table_options,
                use_pyarrow=self.use_pyarrow,
                pyarrow_options=self.pyarrow_options,
            )
        )

    recipe_template = cleandoc("""
        import polars as pl

        df = pl.scan_delta({url}{kwargs})
        """)

    def recipe(self, fmt: DeltaLake, target: Target) -> str:
        # Only the arguments that differ from scan_delta's defaults.
        return self.recipe_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=self.code_storage_options(),
                delta_table_options=self.delta_table_options,
                use_pyarrow=True if self.use_pyarrow else None,
                pyarrow_options=self.pyarrow_options,
            ),
        )
