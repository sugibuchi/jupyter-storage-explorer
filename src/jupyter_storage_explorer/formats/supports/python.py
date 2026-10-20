"""Previews needing no package: text and code (highlighted), Markdown and
JSON from the beginning of the file, and images, which the browser shows."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.base import file_size, head, head_text
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.preview import (
    MarkdownPreview,
    MediaPreview,
    TextPreview,
    TreePreview,
)
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Json, Markdown, Text

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.preview import Preview, PreviewLimits
    from jupyter_storage_explorer.location import Location


def size_note(fs: AbstractFileSystem, path: str, limits: PreviewLimits) -> str:
    """The note under a preview of the file's beginning."""
    size = file_size(fs, path)
    total = f" of {size:,} bytes" if size is not None else ""
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


def text_preview(text: str, language: str | None, note: str = "") -> TextPreview:
    """A text section, highlighted as ``language`` (Pygments' name) if known."""
    return TextPreview(
        text=text, language=language, html=_highlight(text, language), note=note
    )


class TextByPython(FormatSupport):
    """Text and code files, from their beginning, highlighted by their extension."""

    format = Text
    capabilities = ("preview",)

    def preview(
        self,
        fmt: Text,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        text, truncated = head_text(fs, path, limits.max_bytes)
        note = size_note(fs, path, limits) if truncated else ""
        return text_preview(text, fmt.language(path), note)


class MarkdownByPython(FormatSupport):
    """Markdown, rendered by the browser. Before ``TextByPython`` in a list:
    Markdown is a Text format."""

    format = Markdown
    capabilities = ("preview",)

    def preview(
        self,
        fmt: Markdown,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        text, truncated = head_text(fs, path, limits.max_bytes)
        note = size_note(fs, path, limits) if truncated else ""
        return MarkdownPreview(text=text, note=note)


class JsonByPython(FormatSupport):
    """JSON as a tree; as text if it is too large or invalid."""

    format = Json
    capabilities = ("preview",)

    def preview(
        self,
        fmt: Json,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        text, truncated = head_text(fs, path, limits.max_bytes)
        if truncated:
            note = f"{size_note(fs, path, limits)}; too large to show as a tree"
            return text_preview(text, "json", note)
        try:
            return TreePreview(value=json.loads(text))
        except json.JSONDecodeError as exc:
            return text_preview(text, "json", f"Invalid JSON: {exc}")


class ImageByPython(FormatSupport):
    """Images, shown by the browser: their bytes, or a temporary link for
    those too large to send through the kernel."""

    format = Image
    capabilities = ("preview",)

    def preview(
        self,
        fmt: Image,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: PreviewLimits,
    ) -> Preview:
        mime = fmt.mime_type(path)
        size = file_size(fs, path)
        if size is not None and size <= limits.max_whole_file_bytes:
            return MediaPreview(mime=mime, data=head(fs, path, size))
        # Too large to send through the kernel: let the browser fetch it, if the
        # storage can issue a temporary link.
        try:
            return MediaPreview(mime=mime, src=fs.sign(path))
        except NotImplementedError:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to preview (over {limit} MB)") from None
