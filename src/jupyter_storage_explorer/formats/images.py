"""Image files, shown by the browser itself."""

from __future__ import annotations

from jupyter_storage_explorer.formats.base import DataFormat, Target


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

    def mime_type(self, target: Target) -> str:
        """The file's media type, by its extension."""
        return self.mime_types["." + target.name.lower().rsplit(".", 1)[-1]]
