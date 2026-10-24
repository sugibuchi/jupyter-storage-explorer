"""The built-in views and code, which need no engine, only the explorer's
own packages: text and code (highlighted), Markdown and JSON from the
beginning of the file, and images, which the browser shows; and code reading
text and JSON with fsspec, and images with Pillow, for any storage. Their
options are the "python" entry of ``engine_options``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.packages import Fsspec, Pillow
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
    from jupyter_storage_explorer.formats.support import Task
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


READ_TEXT = "Read the text"
LOAD_VALUE = "Load the JSON value"
OPEN_IMAGE = "Open the image"


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
    the file opened, e.g. Pillow), with its options."""

    additional_requirements = (Fsspec(),)
    options_model = FsspecOptions


class TextByPython(OpenedByFsspec):
    """Text and code files: from their beginning, highlighted by their
    extension; their text read with fsspec."""

    format = Text

    def view(
        self, fmt: Text, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
    ) -> View:
        text, truncated = ctx.head_text(limits.max_bytes)
        note = _size_note(ctx, limits) if truncated else ""
        return _text_view(text, fmt.language(ctx.path), note)

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


class MarkdownByPython(FormatSupport):
    """Markdown, rendered by the browser. Before ``TextByPython`` in a list:
    Markdown is a Text format."""

    format = Markdown

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


class JsonByPython(OpenedByFsspec):
    """JSON as a tree, or as text if it is too large or invalid; its value
    loaded with fsspec and Python's json."""

    format = Json

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


class ImageByPython(FormatSupport):
    """Images, shown by the browser: their bytes, or a temporary link for
    those too large to send through the kernel."""

    format = Image

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


class ImageByPillow(OpenedByFsspec):
    """The image, read with fsspec and opened with Pillow; not SVG, which it
    cannot read. Code only, apart from ``ImageByPython``: Pillow, which only
    the code needs, would otherwise be needed to view images."""

    format = Image
    additional_requirements = (Fsspec(), Pillow())

    image_template = cleandoc("""
        import fsspec
        import PIL.Image

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            img = PIL.Image.open(f)
            img.load()
        img
        """)

    def supports(
        self, fmt: Image, ctx: ItemContext, options: SupportOptions, task: Task
    ) -> bool:
        svg = fmt.mime_type(ctx.path) == "image/svg+xml"
        return super().supports(fmt, ctx, options, task) and not svg

    def recipe(
        self, fmt: Image, ctx: ItemContext, options: FsspecOptions
    ) -> dict[str, str]:
        return {
            OPEN_IMAGE: self.image_template.format(
                url=repr(ctx.library_url), kwargs=options.code_kwargs()
            )
        }
