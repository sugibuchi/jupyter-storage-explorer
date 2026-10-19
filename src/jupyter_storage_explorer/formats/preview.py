"""Previews: ``FormatSupport.preview`` returns one of these, and the
frontend renders it, a section of the preview panel, according to its
``kind``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True, kw_only=True)
class PreviewLimits:
    max_bytes: int = 64 * 1024
    max_rows: int = 100
    # Largest file read whole, e.g. images (sent to the browser) and Excel workbooks.
    max_whole_file_bytes: int = 10 * 1024 * 1024


@dataclass(frozen=True, kw_only=True)
class Preview:
    kind: ClassVar[str]
    title: str = ""
    # Shown under the section, e.g. "First 100 rows of 1,234,567".
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class TextPreview(Preview):
    kind: ClassVar[str] = "text"
    text: str
    # Hint for syntax highlighting, e.g. "python", "json", "yaml".
    language: str | None = None
    # ``text`` with syntax highlighting: HTML-escaped, with tokens in
    # <span class="..."> using Pygments' short class names (k, s, c, ...).
    html: str | None = None


@dataclass(frozen=True, kw_only=True)
class MarkdownPreview(Preview):
    """Markdown source; the frontend renders it to (sanitized) HTML."""

    kind: ClassVar[str] = "markdown"
    text: str


@dataclass(frozen=True, kw_only=True)
class TablePreview(Preview):
    kind: ClassVar[str] = "table"
    columns: list[str]
    rows: list[list[Any]]
    dtypes: list[str] | None = None


@dataclass(frozen=True, kw_only=True)
class TreePreview(Preview):
    """Collapsible view of JSON-like data."""

    kind: ClassVar[str] = "tree"
    value: Any


@dataclass(frozen=True, kw_only=True)
class InstallPreview(Preview):
    """Shown instead of a preview when the packages to read the format are missing."""

    kind: ClassVar[str] = "install"
    format: str  # e.g. "Delta Lake table"
    # One per set of requirements that could preview it, most preferred first:
    # the names of its packages still missing, e.g. ["polars", "deltalake"].
    options: list[list[str]]


@dataclass(frozen=True, kw_only=True)
class MediaPreview(Preview):
    """Content the browser renders natively (image, PDF, audio, video), chosen by ``mime``.

    Exactly one of ``data`` (bytes sent to the browser) or ``src`` (e.g. a
    signed URL the browser fetches itself) is set.
    """

    kind: ClassVar[str] = "media"
    mime: str
    data: bytes | None = None
    src: str | None = None
