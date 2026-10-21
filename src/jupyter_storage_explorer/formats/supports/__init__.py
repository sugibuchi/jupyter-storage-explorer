"""The format supports of the explorer itself, needing no engine (python.py):
the built-in views, and code reading files with fsspec or opening images with
Pillow, with their options (``FsspecOptions``). The engines' supports come
with their plugins, e.g. ``jupyter_storage_explorer_polars_support``.

Modules of supports are named after the libraries they use, but import them
only inside methods, so the names never shadow the libraries themselves."""

from jupyter_storage_explorer.formats.supports.python import (
    FsspecOptions,
    ImageByPillow,
    ImageByPython,
    JsonByPython,
    MarkdownByPython,
    TextByPython,
)

__all__ = [
    "FsspecOptions",
    "ImageByPillow",
    "ImageByPython",
    "JsonByPython",
    "MarkdownByPython",
    "TextByPython",
]
