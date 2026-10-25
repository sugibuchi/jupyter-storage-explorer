"""StorageExplorer's actions, and the user's read again (a mixin of the
class): "Reload actions" in the settings menu applies a change to the user's
action files without creating the explorer again."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._explorer.icons import format_icons
from jupyter_storage_explorer._extensions.user_actions import load_user_actions
from jupyter_storage_explorer.formats import Text

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from jupyter_storage_explorer.formats import DataFormat
    from jupyter_storage_explorer.formats.actions import Action


class UserActionsMixin:
    """The explorer's action chain, made of the actions it was given and the
    user's ("reload_actions" reads the user's again).

    What is detected or shown with the former actions is forgotten: the
    folder shown is listed again, as a refresh does. The preview open and the
    tabs keep the actions they were made with."""

    # The actions before the user's (the plugins', the explorer's own and
    # those given), the formats besides the actions', and what the chain is
    # made with: kept by __init__ to make it again.
    _other_actions: list[Action[Any]]
    _chain_formats: list[type[DataFormat]]
    _chain_options: tuple[Mapping[str, Any] | None, Sequence[str]]
    _actions: ActionChain
    _formats: list[DataFormat]
    _config_files: dict[str, tuple[str, Callable[[], Any]]]
    _engines: list[dict[str, str]]
    _engine: str

    def _chain_of(self, users: Sequence[Action[Any]]) -> ActionChain:
        """The chain of the other actions, then ``users``."""
        engine_options, engine_preference = self._chain_options
        return ActionChain(
            [*self._other_actions, *users],
            engine_options,
            formats=self._chain_formats,
            engine_preference=engine_preference,
        )

    def _format_traits(self) -> dict[str, Any]:
        """The traits telling the page of the chain's formats."""
        icons, svgs = format_icons(self._formats)
        return {
            "_format_labels": {f.name: f.label for f in self._formats},
            "_text_formats": [f.name for f in self._formats if isinstance(f, Text)],
            "_format_icons": icons,
            "_file_icon_svgs": svgs,
        }

    def _reload_actions(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "reload_actions": read the user's action files again, and use
        their actions from now on; {"actions": how many, "problems": the files
        left out and why}, or {"error"}, the actions used staying as they
        were. Only with user_actions "enabled", which offers the file."""
        if "actions" not in self._config_files:
            return {"error": "this explorer reads no actions files"}
        try:
            users, problems = load_user_actions(self._other_actions)
            chain = self._chain_of(users)
        except Exception as exc:
            return {"error": error_text(exc)}
        self._actions = chain
        self._formats = chain.formats
        with self.hold_trait_notifications():
            for name, value in self._format_traits().items():
                setattr(self, name, value)
        self._reload_engines()
        self._refresh()
        self._show_selected_format()
        return {"actions": len(users), "problems": problems}

    def _reload_engines(self) -> None:
        """Offer the new chain's engines, keeping the one chosen if it is still
        offered; otherwise the first, which is not the user's choice."""
        engines = self._actions.engines
        self._engines = [{"key": e.key, "label": e.label} for e in engines]
        keys = [e.key for e in engines]
        if self._engine not in keys:
            # As in __init__: _on_engine does not remember it.
            self._engine_ready = False
            try:
                self._engine = keys[0] if keys else ""
            finally:
                self._engine_ready = True
