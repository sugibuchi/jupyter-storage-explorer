"""Formats previewed from the beginning of a text file."""

from __future__ import annotations

import csv
import io
import json
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.format import DataFormat, Target
from jupyter_storage_explorer.formats.frames import (
    pandas_table,
    polars_table,
    rows_note,
)
from jupyter_storage_explorer.formats.preview import (
    MarkdownPreview,
    Preview,
    PreviewLimits,
    TextPreview,
    TreePreview,
)
from jupyter_storage_explorer.formats.requirements import (
    Fsspec,
    Pandas,
    Polars,
    PySpark,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.requirement import Requirements


def _size_note(target: Target, limits: PreviewLimits) -> str:
    total = f" of {target.size:,} bytes" if target.size is not None else ""
    return f"First {limits.max_bytes // 1024} KB{total}"


def _highlight(text: str, language: str | None) -> str | None:
    """``text`` as HTML with syntax highlighting, or None if the language is unknown.

    Pygments escapes the text; tokens get its short CSS classes (k for
    keywords, s for strings, ...), which storage_explorer.css colours.
    """
    if language is None:
        return None
    try:
        # Keep leading and trailing newlines, so the text is shown as it is.
        lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return None
    result = highlight(text, lexer, HtmlFormatter(nowrap=True))
    # Some lexers (e.g. JSON) add a final newline even with ensurenl=False.
    if result.endswith("\n") and not text.endswith(("\n", "\r")):
        result = result[:-1]
    return result


def _text_preview(text: str, language: str | None, note: str = "") -> TextPreview:
    return TextPreview(
        text=text, language=language, html=_highlight(text, language), note=note
    )


class Text(DataFormat):
    name = "text"
    label = "Text"
    # Extension -> syntax highlighting hint. Includes text-based data formats
    # (JSON, CSV, SVG, ...), so those can also be previewed as plain text.
    languages = {  # noqa: RUF012
        ".txt": None, ".log": None, ".md": "markdown", ".rst": None,
        ".py": "python", ".sql": "sql", ".r": "r", ".sh": "shell",
        ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini",
        ".conf": None, ".properties": "properties", ".xml": "xml", ".html": "html",
        ".js": "javascript", ".ts": "typescript", ".java": "java", ".scala": "scala",
        ".json": "json", ".jsonl": "json", ".ndjson": "json", ".csv": None, ".tsv": None, ".svg": "xml",
        ".markdown": "markdown",
    }  # fmt: skip
    extensions = tuple(languages)
    priority = -10  # the fallback: any more specific format is the default
    # No file_icon: files get the icon of their extension (Python, YAML, ...).
    preferred_requirements = ((Fsspec,),)

    def __init__(
        self,
        *,
        fsspec_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the code snippet; ones that look like credentials are left out. Other
        options (``kwargs``) are ignored."""
        self.fsspec_storage_options = fsspec_storage_options

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        language = self.languages.get("." + target.name.lower().rsplit(".", 1)[-1])
        return [
            _text_preview(
                text, language, _size_note(target, limits) if truncated else ""
            )
        ]

    def load_code(self, target: Target, requirements: Requirements) -> str:
        return self.load_code_fsspec(target)

    load_code_fsspec_template = cleandoc("""
        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            text = f.read()
        """)

    def load_code_fsspec(self, target: Target) -> str:
        return self.load_code_fsspec_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(**snippet_options(self.fsspec_storage_options)),
        )


class Markdown(Text):
    """Markdown, rendered in the browser. A Text subclass: same load code, and still editable."""

    name = "markdown"
    label = "Markdown"
    extensions = (".md", ".markdown")
    file_icon = "markdown"
    priority = 0  # preferred over Text, which stays available through "Preview as"

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        return [
            MarkdownPreview(
                text=text, note=_size_note(target, limits) if truncated else ""
            )
        ]


class Csv(DataFormat):
    name = "csv"
    label = "CSV"
    extensions = (".csv", ".tsv")
    file_icon = "spreadsheet"
    preferred_requirements = ((Polars,), (Pandas,))
    code_only_requirements = ((PySpark,),)
    query_requirements = (Polars,)

    def __init__(
        self,
        *,
        polars_storage_options: Mapping[str, Any] | None = None,
        polars_credential_provider: Any = "auto",
        pandas_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``polars_storage_options`` and ``polars_credential_provider``: for
        polars' ``scan_csv``, in the data browser and the polars code snippet
        (as ``read_csv``'s). ``pandas_storage_options``: for pandas'
        ``read_csv`` in the pandas snippet.

        In snippets, storage options that look like credentials are left out,
        as is the credential provider. Other options (``kwargs``) are ignored.
        """
        self.polars_storage_options = polars_storage_options
        self.polars_credential_provider = polars_credential_provider
        self.pandas_storage_options = pandas_storage_options

    def _separator(self, name: str, sample: str) -> str:
        """The separator of a file named (or located at) ``name``, from a sample of it."""
        if name.lower().endswith(".tsv"):
            return "\t"
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def scan(self, url: str, is_dir: bool) -> Any:
        pl = Polars().load()
        storage = {
            "storage_options": self.polars_storage_options,
            "credential_provider": self.polars_credential_provider,
        }
        # The first lines, read by polars too, so any URL it reads works.
        sample = "\n".join(pl.scan_lines(url, **storage).head(20).collect()["line"])
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        return pl.scan_csv(
            url,
            separator=self._separator(url, sample),
            truncate_ragged_lines=True,
            try_parse_dates=True,
            **storage,
        )

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        if Polars in requirements:
            return self.preview_with_polars(target, limits)
        return self.preview_with_pandas(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pl = Polars().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pl.read_csv(
            io.BytesIO(text.encode()),
            separator=self._separator(target.name, text),
            n_rows=limits.max_rows,
            truncate_ragged_lines=True,
        )
        return [
            polars_table(
                df, note=rows_note(df.height, truncated or df.height == limits.max_rows)
            )
        ]

    def preview_with_pandas(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pd = Pandas().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pd.read_csv(
            io.StringIO(text),
            sep=self._separator(target.name, text),
            nrows=limits.max_rows,
        )
        return [
            pandas_table(
                df, note=rows_note(len(df), truncated or len(df) == limits.max_rows)
            )
        ]

    def load_code(self, target: Target, requirements: Requirements) -> str:
        if PySpark in requirements:
            return self.load_code_pyspark(target)
        if Polars in requirements:
            return self.load_code_polars(target)
        return self.load_code_pandas(target)

    def _code_separator(self, target: Target) -> str | None:
        """The file's separator for load code; None for ",", the default."""
        sep = self._separator(target.name, target.head_text(4096)[0])
        return None if sep == "," else sep

    load_code_polars_template = cleandoc("""
        import polars as pl

        df = pl.read_csv({url}{kwargs})
        """)

    def load_code_polars(self, target: Target) -> str:
        return self.load_code_polars_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                separator=self._code_separator(target),
                storage_options=snippet_options(self.polars_storage_options) or None,
            ),
        )

    load_code_pandas_template = cleandoc("""
        import pandas as pd

        df = pd.read_csv({url}{kwargs})
        """)

    def load_code_pandas(self, target: Target) -> str:
        return self.load_code_pandas_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                sep=self._code_separator(target),
                storage_options=snippet_options(self.pandas_storage_options) or None,
            ),
        )

    load_code_pyspark_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.csv({url}, header=True, inferSchema=True{kwargs})
        """)

    def load_code_pyspark(self, target: Target) -> str:
        # Spark reads with its own storage configuration.
        return self.load_code_pyspark_template.format(
            url=repr(spark_url(target.url)),
            kwargs=format_kwargs(sep=self._code_separator(target)),
        )


class Json(DataFormat):
    name = "json"
    label = "JSON"
    extensions = (".json",)
    file_icon = "json"
    preferred_requirements = ((Fsspec,), (Polars,), (Pandas,))

    def __init__(
        self,
        *,
        fsspec_storage_options: Mapping[str, Any] | None = None,
        pandas_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the fsspec snippet. ``pandas_storage_options``: for pandas'
        ``read_json`` in the pandas snippet. (polars' ``read_json`` takes no
        storage options.)

        Storage options that look like credentials are left out. Other
        options (``kwargs``) are ignored.
        """
        self.fsspec_storage_options = fsspec_storage_options
        self.pandas_storage_options = pandas_storage_options

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        if truncated:
            note = f"{_size_note(target, limits)}; too large to show as a tree"
            return [_text_preview(text, "json", note)]
        try:
            return [TreePreview(value=json.loads(text))]
        except json.JSONDecodeError as exc:
            return [_text_preview(text, "json", f"Invalid JSON: {exc}")]

    def load_code(self, target: Target, requirements: Requirements) -> str:
        if Polars in requirements:
            return self.load_code_polars(target)
        if Pandas in requirements:
            return self.load_code_pandas(target)
        return self.load_code_fsspec(target)

    load_code_fsspec_template = cleandoc("""
        import json

        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            data = json.load(f)
        """)

    def load_code_fsspec(self, target: Target) -> str:
        return self.load_code_fsspec_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(**snippet_options(self.fsspec_storage_options)),
        )

    load_code_polars_template = cleandoc("""
        import polars as pl

        df = pl.read_json({url})
        """)

    def load_code_polars(self, target: Target) -> str:
        # polars' read_json takes no storage options.
        return self.load_code_polars_template.format(url=repr(target.url))

    load_code_pandas_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}{kwargs})
        """)

    def load_code_pandas(self, target: Target) -> str:
        return self.load_code_pandas_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=snippet_options(self.pandas_storage_options) or None
            ),
        )


class JsonLines(DataFormat):
    name = "json-lines"
    label = "JSON Lines"
    extensions = (".jsonl", ".ndjson")
    file_icon = "json"
    preferred_requirements = ((Polars,), (Pandas,))
    code_only_requirements = ((PySpark,),)
    query_requirements = (Polars,)

    def __init__(
        self,
        *,
        polars_storage_options: Mapping[str, Any] | None = None,
        polars_credential_provider: Any = "auto",
        pandas_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``polars_storage_options`` and ``polars_credential_provider``: for
        polars' ``scan_ndjson``, in the data browser and the polars code
        snippet. ``pandas_storage_options``: for pandas' ``read_json`` in the
        pandas snippet.

        In snippets, storage options that look like credentials are left out,
        as is the credential provider. Other options (``kwargs``) are ignored.
        """
        self.polars_storage_options = polars_storage_options
        self.polars_credential_provider = polars_credential_provider
        self.pandas_storage_options = pandas_storage_options

    def scan(self, url: str, is_dir: bool) -> Any:
        return (
            Polars()
            .load()
            .scan_ndjson(
                url,
                storage_options=self.polars_storage_options,
                credential_provider=self.polars_credential_provider,
            )
        )

    def preview(
        self, target: Target, limits: PreviewLimits, requirements: Requirements
    ) -> list[Preview]:
        if Polars in requirements:
            return self.preview_with_polars(target, limits)
        return self.preview_with_pandas(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pl = Polars().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pl.read_ndjson(io.BytesIO(text.encode()), n_rows=limits.max_rows)
        more = truncated or df.height == limits.max_rows
        return [polars_table(df, note=rows_note(df.height, more, "records"))]

    def preview_with_pandas(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pd = Pandas().load()
        text, truncated = target.head_text(limits.max_bytes)
        df = pd.read_json(io.StringIO(text), lines=True, nrows=limits.max_rows)
        more = truncated or len(df) == limits.max_rows
        return [pandas_table(df, note=rows_note(len(df), more, "records"))]

    def load_code(self, target: Target, requirements: Requirements) -> str:
        if PySpark in requirements:
            return self.load_code_pyspark(target)
        if Polars in requirements:
            return self.load_code_polars(target)
        return self.load_code_pandas(target)

    load_code_polars_template = cleandoc("""
        import polars as pl

        df = pl.scan_ndjson({url}{kwargs})
        """)

    def load_code_polars(self, target: Target) -> str:
        return self.load_code_polars_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=snippet_options(self.polars_storage_options) or None
            ),
        )

    load_code_pandas_template = cleandoc("""
        import pandas as pd

        df = pd.read_json({url}, lines=True{kwargs})
        """)

    def load_code_pandas(self, target: Target) -> str:
        return self.load_code_pandas_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(
                storage_options=snippet_options(self.pandas_storage_options) or None
            ),
        )

    # Spark reads JSON Lines (one record per line) by default.
    load_code_pyspark_template = cleandoc("""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        df = spark.read.json({url})
        """)

    def load_code_pyspark(self, target: Target) -> str:
        # Spark reads with its own storage configuration.
        return self.load_code_pyspark_template.format(url=repr(spark_url(target.url)))
