"""Load code reading files with fsspec, for any storage: text and JSON."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    format_kwargs,
    library_url,
    snippet_options,
)
from jupyter_storage_explorer.formats.packages import Fsspec
from jupyter_storage_explorer.formats.support import FormatSupport, SupportOptions
from jupyter_storage_explorer.formats.text import Json, Text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import ItemContext

READ_TEXT = "Read the text"
LOAD_VALUE = "Load the JSON value"


@dataclass(frozen=True, kw_only=True)
class FsspecOptions(SupportOptions):
    """The options of code opening the file with ``fsspec.open``.

    Attributes
    ----------
    storage_options : mapping or None, default None
        ``fsspec.open``'s keyword arguments in the code; those that look like
        credentials are left out.
    """

    storage_options: Mapping[str, Any] | None = None

    def code_kwargs(self) -> str:
        """``{kwargs}`` of the template: the storage options fit to show."""
        return format_kwargs(**snippet_options(self.storage_options))


class OpenedByFsspec(FormatSupport):
    """Code opening the file with ``fsspec.open`` (also for libraries reading
    the file opened, e.g. Pillow)."""

    options_model = FsspecOptions


class TextByFsspec(OpenedByFsspec):
    """The text, for Text formats (code, logs, Markdown, ...)."""

    format = Text
    engine = Fsspec
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
                url=repr(library_url(ctx.location)), kwargs=options.code_kwargs()
            )
        }


class JsonByFsspec(OpenedByFsspec):
    """The JSON value, with Python's json."""

    format = Json
    engine = Fsspec
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
                url=repr(library_url(ctx.location)), kwargs=options.code_kwargs()
            )
        }
