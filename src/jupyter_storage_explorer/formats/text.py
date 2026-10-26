"""Formats of text files: plain text, and the kinds of text files a format of
their own recognises (code, configuration, Markdown, CSV, JSON, ...).

Each kind is a subclass of ``Text``, so that Text's actions do it too: its
files can always be viewed as plain text, and read as text in code."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING, Any

from pygments.lexers import find_lexer_class_for_filename
from pygments.util import ClassNotFound

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.formats.base import DataFormat
from jupyter_storage_explorer.formats.images import Image

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext


class Text(DataFormat):
    """Plain text: the base of the formats of text files."""

    name = "text"
    label = "Text"
    extensions = (".txt",)
    priority = -10  # the fallback: any more specific format is the default
    # No file_icon: files get the icon of their extension (Python, YAML, ...).

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A kind of text file ranks as any format of its own, not as the
        # fallback: DataFormat's default priority, unless it sets one.
        super().__init_subclass__(**kwargs)
        if "priority" not in cls.__dict__:
            cls.priority = 0

    def language(self, path: str) -> str | None:
        """The language to highlight the file at `path` as (Pygments' name),
        from Pygments' own file name patterns; None for plain text."""
        try:
            lexer = find_lexer_class_for_filename(_paths.basename(path))
        except ClassNotFound:
            return None
        if lexer is None or not lexer.aliases or lexer.aliases[0] == "text":
            return None
        return lexer.aliases[0]


class Log(Text):
    name = "log"
    label = "Log"
    extensions = (".log",)


class ReStructuredText(Text):
    name = "rst"
    label = "reStructuredText"
    extensions = (".rst",)


class PythonScript(Text):
    name = "python-script"
    label = "Python script"
    extensions = (".py",)


class RScript(Text):
    name = "r-script"
    label = "R script"
    extensions = (".r",)


class ShellScript(Text):
    name = "shell-script"
    label = "Shell script"
    extensions = (".sh",)


class Sql(Text):
    name = "sql"
    label = "SQL"
    extensions = (".sql",)


class JavaScript(Text):
    name = "javascript"
    label = "JavaScript"
    extensions = (".js",)


class TypeScript(Text):
    name = "typescript"
    label = "TypeScript"
    extensions = (".ts",)


class Java(Text):
    name = "java"
    label = "Java"
    extensions = (".java",)


class Scala(Text):
    name = "scala"
    label = "Scala"
    extensions = (".scala",)


class Yaml(Text):
    name = "yaml"
    label = "YAML"
    extensions = (".yaml", ".yml")


class Toml(Text):
    name = "toml"
    label = "TOML"
    extensions = (".toml",)


class Ini(Text):
    name = "ini"
    label = "INI"
    extensions = (".ini", ".cfg")


class Conf(Text):
    name = "conf"
    label = "Configuration"
    extensions = (".conf",)


class Properties(Text):
    name = "properties"
    label = "Properties"
    extensions = (".properties",)


class Xml(Text):
    name = "xml"
    label = "XML"
    extensions = (".xml",)


class Html(Text):
    name = "html"
    label = "HTML"
    extensions = (".html",)


class Svg(Image, Text):
    """SVG images: images the browser shows, and XML text too."""

    name = "svg"
    label = "SVG image"
    extensions = (".svg",)
    mime = "image/svg+xml"


class Markdown(Text):
    """Markdown, rendered in the browser. A Text subclass: same load code, and still editable."""

    name = "markdown"
    label = "Markdown"
    extensions = (".md", ".markdown")
    file_icon = "markdown"


class Csv(Text):
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

    def code_separator(self, ctx: ItemContext) -> str | None:
        """The file's separator for load code; None for ",", the default."""
        sep = self.separator(ctx.name, ctx.head_text(4096)[0])
        return None if sep == "," else sep


class Json(Text):
    name = "json"
    label = "JSON"
    extensions = (".json",)
    file_icon = "json"


class JsonLines(Text):
    name = "json-lines"
    label = "JSON Lines"
    extensions = (".jsonl", ".ndjson")
    file_icon = "json"


# The kinds of text files without actions of their own, which explorers
# detect for Text's actions (defaults.py).
TEXT_FORMATS: tuple[type[Text], ...] = (
    Log,
    ReStructuredText,
    PythonScript,
    RScript,
    ShellScript,
    Sql,
    JavaScript,
    TypeScript,
    Java,
    Scala,
    Yaml,
    Toml,
    Ini,
    Conf,
    Properties,
    Xml,
    Html,
    Svg,
)
