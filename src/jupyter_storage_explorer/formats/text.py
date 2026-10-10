"""Formats previewed from the beginning of a text file."""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.base import (
    DataFormat,
    MarkdownPreview,
    Preview,
    PreviewLimits,
    Requirements,
    Target,
    TextPreview,
    TreePreview,
    format_args,
    spark_url,
)
from jupyter_storage_explorer.formats.frames import (
    pandas_table,
    polars_table,
    rows_note,
)
from jupyter_storage_explorer.formats.requirements import (
    Fsspec,
    Pandas,
    Polars,
    PySpark,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    name = "Text"
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
    preferred_requirements = ((Fsspec,),)

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        language = self.languages.get("." + target.name.lower().rsplit(".", 1)[-1])
        return [
            _text_preview(
                text, language, _size_note(target, limits) if truncated else ""
            )
        ]

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        return (
            f"with {Fsspec().code_name()}.open({format_args(target.url, 'rt', **storage_options)}) as f:\n"
            "    text = f.read()"
        )


class Markdown(Text):
    """Markdown, rendered in the browser. A Text subclass: same load code, and still editable."""

    name = "Markdown"
    extensions = (".md", ".markdown")
    priority = 0  # preferred over Text, which stays available through "Preview as"

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        return [
            MarkdownPreview(
                text=text, note=_size_note(target, limits) if truncated else ""
            )
        ]


class Csv(DataFormat):
    name = "CSV"
    extensions = (".csv", ".tsv")
    preferred_requirements = ((Polars,), (Pandas,))
    code_only_requirements = ((PySpark,),)
    query_requirements = (Polars,)

    def _separator(self, name: str, sample: str) -> str:
        """The separator of a file named (or located at) ``name``, from a sample of it."""
        if name.lower().endswith(".tsv"):
            return "\t"
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def scan(self, url: str) -> Any:
        pl = Polars().load()
        # The first lines, read by polars too, so any URL it reads works.
        sample = "\n".join(pl.scan_lines(url).head(20).collect()["line"])
        # try_parse_dates: date columns get date filters (<, >, ...) instead of text ones.
        return pl.scan_csv(
            url,
            separator=self._separator(url, sample),
            truncate_ragged_lines=True,
            try_parse_dates=True,
        )

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        requirements = self.installed_requirements()
        if requirements is None:
            return self.install_hint()
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

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        sep = self._separator(target.name, target.head_text(4096)[0])
        sep = None if sep == "," else sep
        if PySpark in requirements:
            # Spark reads with its own storage configuration, not fsspec's options.
            args = format_args(
                spark_url(target.url), header=True, inferSchema=True, sep=sep
            )
            return f"df = {PySpark().code_name()}.read.csv({args})"
        options = dict(storage_options) or None
        if Polars in requirements:
            return f"df = {Polars().code_name()}.read_csv({format_args(target.url, separator=sep, storage_options=options)})"
        return f"df = {Pandas().code_name()}.read_csv({format_args(target.url, sep=sep, storage_options=options)})"


class Json(DataFormat):
    name = "JSON"
    extensions = (".json",)
    preferred_requirements = ((Fsspec,), (Polars,), (Pandas,))

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        text, truncated = target.head_text(limits.max_bytes)
        if truncated:
            note = f"{_size_note(target, limits)}; too large to show as a tree"
            return [_text_preview(text, "json", note)]
        try:
            return [TreePreview(value=json.loads(text))]
        except json.JSONDecodeError as exc:
            return [_text_preview(text, "json", f"Invalid JSON: {exc}")]

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        options = dict(storage_options) or None
        if Polars in requirements:
            return f"df = {Polars().code_name()}.read_json({format_args(target.url, storage_options=options)})"
        if Pandas in requirements:
            return f"df = {Pandas().code_name()}.read_json({format_args(target.url, storage_options=options)})"
        return (
            "import json\n\n"
            f"with {Fsspec().code_name()}.open({format_args(target.url, 'rt', **storage_options)}) as f:\n"
            "    data = json.load(f)"
        )


class JsonLines(DataFormat):
    name = "JSON Lines"
    extensions = (".jsonl", ".ndjson")
    preferred_requirements = ((Polars,), (Pandas,))
    code_only_requirements = ((PySpark,),)
    query_requirements = (Polars,)

    def scan(self, url: str) -> Any:
        return Polars().load().scan_ndjson(url)

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        requirements = self.installed_requirements()
        if requirements is None:
            return self.install_hint()
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

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        if PySpark in requirements:
            # Spark reads JSON Lines (one record per line) by default, with its
            # own storage configuration, not fsspec's options.
            return f"df = {PySpark().code_name()}.read.json({format_args(spark_url(target.url))})"
        options = dict(storage_options) or None
        if Polars in requirements:
            return f"df = {Polars().code_name()}.read_ndjson({format_args(target.url, storage_options=options)})"
        return f"df = {Pandas().code_name()}.read_json({format_args(target.url, lines=True, storage_options=options)})"
