"""Load code opening images with Pillow."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import library_url
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.packages import Fsspec, Pillow
from jupyter_storage_explorer.formats.supports.fsspec import OpenedByFsspec

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import ItemContext
    from jupyter_storage_explorer.formats.supports.fsspec import FsspecOptions

OPEN_IMAGE = "Open the image"


class ImageByPillow(OpenedByFsspec):
    """The image, read with fsspec (``storage_options``: ``fsspec.open``'s)
    and opened with Pillow; not SVG, which it cannot read."""

    format = Image
    engine = Pillow
    additional_requirements = (Fsspec,)
    capabilities = ("recipe",)

    image_template = cleandoc("""
        import fsspec
        import PIL.Image

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            img = PIL.Image.open(f)
            img.load()
        img
        """)

    def recipe(
        self, fmt: Image, ctx: ItemContext, options: FsspecOptions
    ) -> dict[str, str]:
        if fmt.mime_type(ctx.path) == "image/svg+xml":
            raise self.NotSupported
        return {
            OPEN_IMAGE: self.image_template.format(
                url=repr(library_url(ctx.location)), kwargs=options.code_kwargs()
            )
        }
