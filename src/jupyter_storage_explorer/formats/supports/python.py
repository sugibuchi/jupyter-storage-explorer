"""The built-in actions, which need no engine, only the explorer's own
packages: views of text and code (highlighted), Markdown and JSON from the
beginning of the file, and of images, which the browser shows; and code
reading text and JSON with fsspec, and images with Pillow, for any storage.
Their options are the "python" entry of ``engine_options``.

They are the models of actions for plugins: each a function, its options
class imported at run time (``FsspecOptions`` here), registered in order in
``BUILT_IN_ACTIONS``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from jupyter_storage_explorer.formats.actions import code, register_actions, view
from jupyter_storage_explorer.formats.base import ItemContext
from jupyter_storage_explorer.formats.engine import PythonEngine
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.packages import Fsspec, Pillow
from jupyter_storage_explorer.formats.support import (
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
    View,
    ViewLimits,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


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


# The code's templates: {url} and {kwargs}, the storage options fit to show.
TEXT_TEMPLATE = cleandoc("""
    import fsspec

    with fsspec.open({url}, 'rt'{kwargs}) as f:
        text = f.read()
    """)

JSON_TEMPLATE = cleandoc("""
    import json

    import fsspec

    with fsspec.open({url}, 'rt'{kwargs}) as f:
        data = json.load(f)
    """)

IMAGE_TEMPLATE = cleandoc("""
    import fsspec
    import PIL.Image

    with fsspec.open({url}, 'rb'{kwargs}) as f:
        img = PIL.Image.open(f)
        img.load()
    img
    """)


def _fsspec_code(template: str, ctx: ItemContext, options: FsspecOptions) -> str:
    """``template`` filled for the item."""
    return template.format(
        url=repr(ctx.url_or_local_path), kwargs=options.code_kwargs()
    )


@code(format=Text, engine=PythonEngine, name=READ_TEXT, requires=(Fsspec(),))
def text_code(fmt: Text, ctx: ItemContext, options: FsspecOptions) -> str:
    """Text read with fsspec."""
    return _fsspec_code(TEXT_TEMPLATE, ctx, options)


@view(format=Text, engine=PythonEngine, code=text_code)
def text_view(
    fmt: Text, ctx: ItemContext, options: FsspecOptions, limits: ViewLimits
) -> View:
    """Text and code files: from their beginning, highlighted by their
    extension."""
    text, truncated = ctx.head_text(limits.max_bytes)
    note = _size_note(ctx, limits) if truncated else ""
    return _text_view(text, fmt.language(ctx.path), note)


@view(format=Markdown, engine=PythonEngine)
def markdown_view(
    fmt: Markdown, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
) -> View:
    """Markdown, rendered by the browser. Registered before ``text_view``:
    Markdown is a Text format."""
    text, truncated = ctx.head_text(limits.max_bytes)
    note = _size_note(ctx, limits) if truncated else ""
    return MarkdownView(text=text, note=note)


@code(format=Json, engine=PythonEngine, name=LOAD_VALUE, requires=(Fsspec(),))
def json_code(fmt: Json, ctx: ItemContext, options: FsspecOptions) -> str:
    """The JSON value, loaded with fsspec and Python's json."""
    return _fsspec_code(JSON_TEMPLATE, ctx, options)


@view(format=Json, engine=PythonEngine, code=json_code)
def json_view(
    fmt: Json, ctx: ItemContext, options: FsspecOptions, limits: ViewLimits
) -> View:
    """JSON as a tree, or as text if it is too large or invalid."""
    text, truncated = ctx.head_text(limits.max_bytes)
    if truncated:
        note = f"{_size_note(ctx, limits)}; too large to show as a tree"
        return _text_view(text, "json", note)
    try:
        return TreeView(value=json.loads(text))
    except json.JSONDecodeError as exc:
        return _text_view(text, "json", f"Invalid JSON: {exc}")


@view(format=Image, engine=PythonEngine)
def image_view(
    fmt: Image, ctx: ItemContext, options: SupportOptions, limits: ViewLimits
) -> View:
    """Images, shown by the browser: their bytes, or a temporary link for
    those too large to send through the kernel."""
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


def _not_svg(fmt: Image, ctx: ItemContext, options: SupportOptions) -> bool:
    """Whether Pillow can open the image: not SVG."""
    return fmt.mime_type(ctx.path) != "image/svg+xml"


@code(
    format=Image,
    engine=PythonEngine,
    name=OPEN_IMAGE,
    requires=(Fsspec(), Pillow()),
    check=_not_svg,
)
def image_code(fmt: Image, ctx: ItemContext, options: FsspecOptions) -> str:
    """The image, read with fsspec and opened with Pillow. Pillow is needed
    by this code only: images are viewed without it."""
    return _fsspec_code(IMAGE_TEMPLATE, ctx, options)


# In the order tried: Markdown before Text, of which it is one.
BUILT_IN_ACTIONS = register_actions(
    json_view,
    json_code,
    markdown_view,
    text_view,
    text_code,
    image_view,
    image_code,
)
