"""Load code reading files with fsspec, for any storage: text and JSON."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import format_kwargs, snippet_options
from jupyter_storage_explorer.formats.requirements import Fsspec
from jupyter_storage_explorer.formats.support import FormatSupport
from jupyter_storage_explorer.formats.text import Json, Text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.base import Target


class OpenedByFsspec(FormatSupport):
    """Code opening the file with ``fsspec.open`` (also for libraries reading
    the file opened, e.g. Pillow)."""

    def __init__(self, *, storage_options: Mapping[str, Any] | None = None) -> None:
        """``storage_options``: ``fsspec.open``'s keyword arguments in the
        code; ones that look like credentials are left out."""
        self.storage_options = storage_options

    def code_kwargs(self) -> str:
        """``{kwargs}`` of the template: the storage options fit to show."""
        return format_kwargs(**snippet_options(self.storage_options))


class TextByFsspec(OpenedByFsspec):
    """The text, for Text formats (code, logs, Markdown, ...)."""

    format = Text
    use = Fsspec
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            text = f.read()
        """)

    def recipe(self, fmt: Text, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(target.url), kwargs=self.code_kwargs()
        )


class JsonByFsspec(OpenedByFsspec):
    """The JSON value, with Python's json."""

    format = Json
    use = Fsspec
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        import json

        import fsspec

        with fsspec.open({url}, 'rt'{kwargs}) as f:
            data = json.load(f)
        """)

    def recipe(self, fmt: Json, target: Target) -> str:
        return self.recipe_template.format(
            url=repr(target.url), kwargs=self.code_kwargs()
        )
