"""Load code opening images with Pillow."""

from __future__ import annotations

from inspect import cleandoc
from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.base import library_url
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.requirements import Fsspec, Pillow
from jupyter_storage_explorer.formats.supports.fsspec import OpenedByFsspec

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.location import Location


class ImageByPillow(OpenedByFsspec):
    """The image, read with fsspec (``storage_options``: ``fsspec.open``'s)
    and opened with Pillow; not SVG, which it cannot read."""

    format = Image
    use = Pillow
    additional_requirements = (Fsspec,)
    capabilities = ("recipe",)

    recipe_template = cleandoc("""
        import fsspec
        import PIL.Image

        with fsspec.open({url}, 'rb'{kwargs}) as f:
            img = PIL.Image.open(f)
            img.load()
        img
        """)

    def recipe(
        self,
        fmt: Image,
        location: Location,
        fs: AbstractFileSystem,
        path: str,
        is_dir: bool,
    ) -> str:
        if fmt.mime_type(path) == "image/svg+xml":
            raise self.NotSupported
        return self.recipe_template.format(
            url=repr(library_url(location)), kwargs=self.code_kwargs()
        )
