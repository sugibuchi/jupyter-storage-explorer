"""The predefined actions explorers use whatever plugins are installed
(``DEFAULT_ACTIONS``): the actions needing no engine. The engines' actions
(polars, pandas, PySpark, ...) come with their plugins. The formats explorers
detect whatever plugins are installed are in ``formats/defaults.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.actions.python import BUILT_IN_ACTIONS

if TYPE_CHECKING:
    from jupyter_storage_explorer.actions.base import Action

# The actions explorers use after their plugins', before those they are given
# and the user's.
DEFAULT_ACTIONS: tuple[Action[Any], ...] = BUILT_IN_ACTIONS
