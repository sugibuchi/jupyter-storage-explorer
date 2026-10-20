"""What needs no package beyond the explorer's own: the built-in views (no
engine) of text and code (highlighted), Markdown and JSON from the beginning
of the file, and images, which the browser shows; and code reading text and
JSON with fsspec, for any storage (``FsspecEngine``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.engine import Engine
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.packages import Fsspec
from jupyter_storage_explorer.formats.support import (
    FormatSupport,
    SupportOptions,
    format_kwargs,
    secret_dict_field,
)
from jupyter_storage_explorer.formats.text import Json, Markdown, Text
from jupyter_storage_explorer.formats.view import (
    MarkdownView,
    MediaView,
    TextView,
    TreeView,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.view import View, ViewLimits


def _size_note(ctx: ItemContext, limits: ViewLimits) -> str:
    """The note under a view of the file's beginning."""
    total = f" of {ctx.size:,} bytes" if ctx.size is not None else ""
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
        self, fmt: Text, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
    ) -> View:
        text, truncated = ctx.head_text(limits.max_bytes)
        note = _size_note(ctx, limits) if truncated else ""
        return _text_view(text, fmt.language(ctx.path), note)


class MarkdownByPython(FormatSupport):
    """Markdown, rendered by the browser. Before ``TextByPython`` in a list:
    Markdown is a Text format."""

    format = Markdown
    capabilities = ("view",)

    def view(
        self,
        fmt: Markdown,
        ctx: ItemContext,
        options: SupportOptions,
        limits: ViewLimits,
    ) -> View:
        text, truncated = ctx.head_text(limits.max_bytes)
        note = _size_note(ctx, limits) if truncated else ""
        return MarkdownView(text=text, note=note)


class JsonByPython(FormatSupport):
    """JSON as a tree; as text if it is too large or invalid."""

    format = Json
    capabilities = ("view",)

    def view(
        self, fmt: Json, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
    ) -> View:
        text, truncated = ctx.head_text(limits.max_bytes)
        if truncated:
            note = f"{_size_note(ctx, limits)}; too large to show as a tree"
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
        self, fmt: Image, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
    ) -> View:
        mime = fmt.mime_type(ctx.path)
        size = ctx.size
        if size is not None and size <= limits.max_whole_file_bytes:
            return MediaView(mime=mime, data=ctx.head(size))
        # Too large to send through the kernel: let the browser fetch it, if the
        # storage can issue a temporary link.
        try:
            return MediaView(mime=mime, src=ctx.fs.sign(ctx.path))
        except NotImplementedError:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to view (over {limit} MB)") from None


# --- Code reading files with fsspec ---

READ_TEXT = "Read the text"
LOAD_VALUE = "Load the JSON value"


class FsspecEngine(Engine):
    """Files read with fsspec: code only (text, JSON values)."""

    key = "fsspec"
    label = "fsspec"
    requirements = (Fsspec(),)


@dataclass(frozen=True, kw_only=True)
class FsspecOptions(SupportOptions):
    """The options of code opening the file with ``fsspec.open``.

    Attributes
    ----------
    storage_options : mapping or None, default None
        ``fsspec.open``'s keyword arguments in the code; those that look like
        credentials are left out.
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

    def code_kwargs(self) -> str:
        """``{kwargs}`` of the template: the storage options fit to show."""
        return format_kwargs(**(self.code_value("storage_options") or {}))


class OpenedByFsspec(FormatSupport):
    """Code opening the file with ``fsspec.open`` (also for libraries reading
    the file opened, e.g. Pillow)."""

    options_model = FsspecOptions


class TextByFsspec(OpenedByFsspec):
    """The text, for Text formats (code, logs, Markdown, ...)."""

    format = Text
    engine = FsspecEngine
    capabilities = ("recipe",)

    text_template = cleandoc("""
        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            text = f.read()
        """)

    def recipe(
        self, fmt: Text, ctx: ItemContext, options: FsspecOptions
    ) -> dict[str, str]:
        return {
            READ_TEXT: self.text_template.format(
                url=repr(ctx.library_url), kwargs=options.code_kwargs()
            )
        }


class JsonByFsspec(OpenedByFsspec):
    """The JSON value, with Python's json."""

    format = Json
    engine = FsspecEngine
    capabilities = ("recipe",)

    value_template = cleandoc("""
        import json

        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            data = json.load(f)
        """)

    def recipe(
        self, fmt: Json, ctx: ItemContext, options: FsspecOptions
    ) -> dict[str, str]:
        return {
            LOAD_VALUE: self.value_template.format(
                url=repr(ctx.library_url), kwargs=options.code_kwargs()
            )
        }
