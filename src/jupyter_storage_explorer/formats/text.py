"""Formats of text files: plain text and code, Markdown, CSV, JSON, JSON Lines."""

from __future__ import annotations

import csv

from jupyter_storage_explorer.formats.format import DataFormat, Target


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

    def language(self, target: Target) -> str | None:
        """The language to highlight the file as (Pygments' name), if known."""
        return self.languages.get("." + target.name.lower().rsplit(".", 1)[-1])


class Markdown(Text):
    """Markdown, rendered in the browser. A Text subclass: same load code, and still editable."""

    name = "markdown"
    label = "Markdown"
    extensions = (".md", ".markdown")
    file_icon = "markdown"
    priority = 0  # preferred over Text, which stays available through "Preview as"


class Csv(DataFormat):
    name = "csv"
    label = "CSV"
    extensions = (".csv", ".tsv")
    file_icon = "spreadsheet"

    @staticmethod
    def separator(name: str, sample: str) -> str:
        """The separator of a file named (or located at) ``name``, from a sample of it."""
        if name.lower().endswith(".tsv"):
            return "\t"
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def code_separator(self, target: Target) -> str | None:
        """The file's separator for load code; None for ",", the default."""
        sep = self.separator(target.name, target.head_text(4096)[0])
        return None if sep == "," else sep


class Json(DataFormat):
    name = "json"
    label = "JSON"
    extensions = (".json",)
    file_icon = "json"


class JsonLines(DataFormat):
    name = "json-lines"
    label = "JSON Lines"
    extensions = (".jsonl", ".ndjson")
    file_icon = "json"
