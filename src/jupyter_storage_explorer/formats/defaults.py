"""The predefined formats and actions explorers use whatever plugins are
installed (``DEFAULT_FORMATS``, ``DEFAULT_ACTIONS``): the standard formats,
always detected, and the actions needing no engine. The engines' actions
(polars, pandas, PySpark, ...) come with their plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.delta import DeltaLake
from jupyter_storage_explorer.formats.excel import Excel
from jupyter_storage_explorer.formats.images import Image
from jupyter_storage_explorer.formats.parquet import Parquet
from jupyter_storage_explorer.formats.python import BUILT_IN_ACTIONS
from jupyter_storage_explorer.formats.text import Csv, Json, JsonLines, Markdown, Text

if TYPE_CHECKING:
    from jupyter_storage_explorer.formats.actions import Action
    from jupyter_storage_explorer.formats.base import DataFormat
    from jupyter_storage_explorer.formats.support import FormatSupport

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
    Text,
    Image,
)

# The actions explorers use after those they are given and their plugins'.
DEFAULT_ACTIONS: tuple[Action[Any], ...] = BUILT_IN_ACTIONS

# The supports of the former interface explorers used by default: none, as
# the built-in ones are actions now. To be removed with FormatSupport.
DEFAULT_SUPPORTS: tuple[type[FormatSupport], ...] = ()


def default_supports() -> list[FormatSupport]:
    """The ``DEFAULT_SUPPORTS``, created: none. To be removed with
    ``FormatSupport``."""
    return []
