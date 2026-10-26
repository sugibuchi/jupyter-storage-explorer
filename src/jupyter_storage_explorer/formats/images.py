"""Image files, shown by the browser itself: ``Image``, the base of a format
for each kind, e.g. ``Png``. SVG images, text too, are text.py's ``Svg``."""

from __future__ import annotations

from typing import ClassVar

from jupyter_storage_explorer.formats.base import DataFormat


class Image(DataFormat):
    """The base of the formats of images, which matches no file itself: its
    actions do every kind.

    Attributes
    ----------
    mime : str
        The media type of the kind's files, e.g. "image/png".
    """

    name = "image"
    label = "Image"
    file_icon = "image"
    mime: ClassVar[str]

    def mime_type(self, path: str) -> str:
        """The media type of the file at `path`: its kind's."""
        return self.mime


class Png(Image):
    name = "png"
    label = "PNG image"
    extensions = (".png",)
    mime = "image/png"


class Jpeg(Image):
    name = "jpeg"
    label = "JPEG image"
    extensions = (".jpg", ".jpeg")
    mime = "image/jpeg"


class Gif(Image):
    name = "gif"
    label = "GIF image"
    extensions = (".gif",)
    mime = "image/gif"


class Webp(Image):
    name = "webp"
    label = "WebP image"
    extensions = (".webp",)
    mime = "image/webp"


class Bmp(Image):
    name = "bmp"
    label = "BMP image"
    extensions = (".bmp",)
    mime = "image/bmp"


class Ico(Image):
    name = "ico"
    label = "Icon"
    extensions = (".ico",)
    mime = "image/x-icon"


class Avif(Image):
    name = "avif"
    label = "AVIF image"
    extensions = (".avif",)
    mime = "image/avif"


# The kinds of images, which explorers detect for Image's actions
# (defaults.py), besides text.py's Svg.
IMAGE_FORMATS: tuple[type[Image], ...] = (Png, Jpeg, Gif, Webp, Bmp, Ico, Avif)
