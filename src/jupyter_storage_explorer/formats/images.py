"""Image files, shown by the browser itself."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import format_kwargs, snippet_options
from jupyter_storage_explorer.formats.format import DataFormat, Recipe, Target
from jupyter_storage_explorer.formats.preview import (
    MediaPreview,
    Preview,
    PreviewLimits,
)
from jupyter_storage_explorer.formats.requirements import Fsspec, Pillow

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jupyter_storage_explorer.formats.requirement import Requirements


class Image(DataFormat):
    name = "image"
    label = "Image"
    mime_types = {  # noqa: RUF012
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp", ".ico": "image/x-icon",
        ".avif": "image/avif", ".svg": "image/svg+xml",
    }  # fmt: skip
    extensions = tuple(mime_types)
    file_icon = "image"
    preferred_requirements = ((Pillow, Fsspec),)

    def __init__(
        self,
        *,
        fsspec_storage_options: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``fsspec_storage_options``: ``fsspec.open``'s keyword arguments in
        the code snippet; ones that look like credentials are left out. Other
        options (``kwargs``) are ignored."""
        self.fsspec_storage_options = fsspec_storage_options

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        mime = self.mime_types["." + target.name.lower().rsplit(".", 1)[-1]]
        if target.size is not None and target.size <= limits.max_whole_file_bytes:
            return [MediaPreview(mime=mime, data=target.head(target.size))]
        # Too large to send through the kernel: let the browser fetch it, if the
        # storage can issue a temporary link.
        try:
            return [MediaPreview(mime=mime, src=target.fs.sign(target.path))]
        except NotImplementedError:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to preview (over {limit} MB)") from None

    def recipes(self, target: Target) -> list[Recipe]:
        if target.name.lower().endswith(".svg"):
            return []  # Pillow cannot read SVG.
        return super().recipes(target)

    def load_code(self, target: Target, requirements: Requirements) -> str:
        return self.load_code_pillow(target)

    load_code_pillow_template = cleandoc("""
        import fsspec
        import PIL.Image

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            img = PIL.Image.open(f)
            img.load()
        img
        """)

    def load_code_pillow(self, target: Target) -> str:
        return self.load_code_pillow_template.format(
            url=repr(target.url),
            kwargs=format_kwargs(**snippet_options(self.fsspec_storage_options)),
        )
