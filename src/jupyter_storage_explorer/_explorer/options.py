"""StorageExplorer's arguments: the values they take, and what is made of
them, checked when the explorer is created."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer._explorer.actions import ActionChain
    from jupyter_storage_explorer.engine import EngineOptions

# The values of tree_view and preview_panel, and of layout.
PANEL_STATES = ("open", "closed", "disabled")
LAYOUTS = ("standard", "sidebar")

# The values of unsafe_mode: offered by the user's switch, always, or never.
UNSAFE_MODES = ("on_demand", "always", "blocked")

# The values of user_actions: the actions of the user's files used, or not.
USER_ACTIONS = ("enabled", "disabled")

# The values of common_config: the settings of the common.py files taken, or not.
COMMON_CONFIGS = ("enabled", "disabled")

# The values of logging_menu: the settings menu's Logging, and log files, or
# neither.
LOGGING_MENUS = ("enabled", "disabled")

# The file list's columns the user can show besides Name (the settings menu's
# Columns), in their order; and those shown by default, per layout.
LIST_COLUMNS = ("size", "mtime", "ctime", "format")
DEFAULT_COLUMNS = {"standard": ["size", "mtime"], "sidebar": ["size"]}


def check_choice(name: str, value: Any, choices: Sequence[str]) -> None:
    if value not in choices:
        raise ValueError(
            f"{name} must be one of {', '.join(map(repr, choices))}, not {value!r}"
        )


def known_columns(columns: Sequence[str]) -> list[str]:
    """``columns`` that the list has, in its order (a file written by another
    version may name others)."""
    return [c for c in LIST_COLUMNS if c in columns]


def code_engines(
    code_snippet: str | Sequence[str], actions: ActionChain
) -> frozenset[str] | None:
    """The engines' keys whose code "Python code" shows: None for all
    ("enabled"), none for "disabled", else those named that an action has
    (its engine's key, "python" for the built-in code); names no
    action has are left out with a warning, as a launcher shared by
    environments with other plugins may name them."""
    if code_snippet == "enabled":
        return None
    if code_snippet == "disabled":
        return frozenset()
    if isinstance(code_snippet, str) or not all(
        isinstance(key, str) for key in code_snippet
    ):
        raise ValueError(
            f'code_snippet must be "enabled", "disabled" or a list of engine keys, '
            f"not {code_snippet!r}"
        )
    known = actions.engine_keys()
    if unknown := sorted(set(code_snippet) - known):
        warnings.warn(
            f"code_snippet: no action of {', '.join(unknown)} (left out); "
            f"engines: {', '.join(sorted(known))}",
            RuntimeWarning,
            stacklevel=4,  # the code creating the explorer
        )
    return frozenset(code_snippet) & known


def engine_options(
    engine_options: EngineOptions | None, format_options: EngineOptions | None
) -> EngineOptions | None:
    """``engine_options``, or ``format_options``, its former name, given
    instead. To be removed in the major release, with ``format_options``."""
    if format_options is None:
        return engine_options
    if engine_options is not None:
        raise ValueError("give engine_options only: format_options is its former name")
    return format_options
