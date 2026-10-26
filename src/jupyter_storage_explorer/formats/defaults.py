"""The predefined formats explorers detect whatever plugins are installed
(``DEFAULT_FORMATS``). The actions explorers use whatever plugins are
installed are in ``actions/defaults.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import IMAGE_FORMATS, Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.text import (
    TEXT_FORMATS,
    Csv,
    Json,
    JsonLines,
    Markdown,
    Text,
)

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import DataFormat

# The formats explorers detect even without an action installed for them, so
# that a Parquet file is one, with its icon, before an engine's plugin is
# installed. Plugins' actions share them (e.g. Parquet's layout). On a tie
# in priority, the format listed first wins.
DEFAULT_FORMATS: tuple[type[DataFormat], ...] = (
    DeltaLake,
    Parquet,
    Csv,
    Excel,
    Json,
    JsonLines,
    Markdown,
    *TEXT_FORMATS,
    Text,
    *IMAGE_FORMATS,
    Image,
)
