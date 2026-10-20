"""Views needing no package: text and code (highlighted), Markdown and
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
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Json, Markdown, Text
from jupyter_storage_explorer.formats.view import (
    MarkdownView,
    MediaView,
    TextView,
    TreeView,
)

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.formats.view import View, ViewLimits
    from jupyter_storage_explorer.location import Location


def _size_note(fs: AbstractFileSystem, path: str, limits: ViewLimits) -> str:
    """The note under a view of the file's beginning."""
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


def _text_view(text: str, language: str | None, note: str = "") -> TextView:
    """A text section, highlighted as ``language`` (Pygments' name) if known."""
    return TextView(
        text=text, language=language, html=_highlight(text, language), note=note
    )


class TextByPython(FormatSupport):
    """Text and code files, from their beginning, highlighted by their extension."""

    format = Text
    capabilities = ("view",)

    def view(
        self,
        fmt: Text,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        text, truncated = head_text(fs, path, limits.max_bytes)
        note = _size_note(fs, path, limits) if truncated else ""
        return _text_view(text, fmt.language(path), note)


class MarkdownByPython(FormatSupport):
    """Markdown, rendered by the browser. Before ``TextByPython`` in a list:
    Markdown is a Text format."""

    format = Markdown
    capabilities = ("view",)

    def view(
        self,
        fmt: Markdown,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        text, truncated = head_text(fs, path, limits.max_bytes)
        note = _size_note(fs, path, limits) if truncated else ""
        return MarkdownView(text=text, note=note)


class JsonByPython(FormatSupport):
    """JSON as a tree; as text if it is too large or invalid."""

    format = Json
    capabilities = ("view",)

    def view(
        self,
        fmt: Json,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        text, truncated = head_text(fs, path, limits.max_bytes)
        if truncated:
            note = f"{_size_note(fs, path, limits)}; too large to show as a tree"
            return _text_view(text, "json", note)
        try:
            return TreeView(value=json.loads(text))
        except json.JSONDecodeError as exc:
            return _text_view(text, "json", f"Invalid JSON: {exc}")


class ImageByPython(FormatSupport):
    """Images, shown by the browser: their bytes, or a temporary link for
    those too large to send through the kernel."""

    format = Image
    capabilities = ("view",)

    def view(
        self,
        fmt: Image,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
        *,
        limits: ViewLimits,
    ) -> View:
        mime = fmt.mime_type(path)
        size = file_size(fs, path)
        if size is not None and size <= limits.max_whole_file_bytes:
            return MediaView(mime=mime, data=head(fs, path, size))
        # Too large to send through the kernel: let the browser fetch it, if the
        # storage can issue a temporary link.
        try:
            return MediaView(mime=mime, src=fs.sign(path))
        except NotImplementedError:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to view (over {limit} MB)") from None
