"""The predefined formats and supports explorers use whatever plugins are
installed (``DEFAULT_FORMATS``, ``default_supports()``): the standard formats,
always detected, and the supports needing no engine. The engines' supports
(polars, pandas, PySpark, ...) come with their plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.supports.python import (
    ImageByPillow,
    ImageByPython,
    JsonByPython,
    MarkdownByPython,
    TextByPython,
)
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport

# The formats explorers detect even without a support installed for them, so
# that a Parquet file is one, with its icon, before an engine's plugin is
# installed. Plugins' supports share them (e.g. Parquet's layout). On a tie
# in priority, the format listed first wins.
DEFAULT_FORMATS: tuple[type[DataFormat], ...] = (
    DeltaLake,
    Parquet,
    Csv,
    Excel,
    Json,
    JsonLines,
    Markdown,
    Text,
    Image,
)

# The supports explorers use after those they are given and their plugins';
# ``default_supports`` creates them. MarkdownByPython comes before
# TextByPython: Markdown is a Text format.
DEFAULT_SUPPORTS: tuple[type[FormatSupport], ...] = (
    JsonByPython,
    MarkdownByPython,
    TextByPython,
    ImageByPython,
    ImageByPillow,
)


def default_supports() -> list[FormatSupport]:
    """The ``DEFAULT_SUPPORTS``, created; their options are given by the
    ``SupportChain`` using them."""
    return [cls() for cls in DEFAULT_SUPPORTS]
