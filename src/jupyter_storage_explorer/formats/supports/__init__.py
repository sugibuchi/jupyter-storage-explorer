"""The actions of the explorer itself, needing no engine (python.py): the
built-in views, and code reading files with fsspec or opening images with
Pillow, with their options (``FsspecOptions``). The engines' actions come
with their plugins, e.g. ``jupyter_storage_explorer_polars_support``.

Modules of actions are named after the libraries they use, but import them
only inside functions, so the names never shadow the libraries themselves."""

from jupyter_storage_explorer.formats.supports.python import (
    BUILT_IN_ACTIONS,
    FsspecOptions,
    image_code,
    image_view,
    json_code,
    json_view,
    markdown_view,
    text_code,
    text_view,
)

__all__ = [
    "BUILT_IN_ACTIONS",
    "FsspecOptions",
    "image_code",
    "image_view",
    "json_code",
    "json_view",
    "markdown_view",
    "text_code",
    "text_view",
]
