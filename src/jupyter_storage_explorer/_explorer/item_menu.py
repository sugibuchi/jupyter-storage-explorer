"""StorageExplorer's right-click menu: the formats, views and code of the
item clicked (a mixin of the class)."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer._errors import error_text
from jupyter_storage_explorer.actions.python import PythonEngine

if TYPE_CHECKING:
    from jupyter_storage_explorer._explorer.actions import Recipe
    from jupyter_storage_explorer.actions import ViewAction
    from jupyter_storage_explorer.base import ItemContext
    from jupyter_storage_explorer.formats import DataFormat


def _recipe_engine(recipe: Recipe) -> str:
    """The key of a recipe's engine, as ``code_snippet`` names it: "python"
    for the built-in code (``PythonEngine``)."""
    return recipe.engine.key if recipe.engine is not None else PythonEngine.key


class ItemMenuMixin:
    """The rows of the right-click menu only the kernel knows ("menu_info"):
    "Preview", "Preview as", "View in new tab as" and "Python code"."""

    def _answer_menu_info(self, content: dict[str, Any]) -> None:
        """Answer "menu_info", the right-click menu's (see ``_menu_info``).
        The item's detection and its recipes may read it (e.g. a CSV file's
        separator), so they run as a load (``_loader``), sharing the click's
        detection (``_detection``); the reply is made on the main thread."""
        detection = self._detection(content["path"], self._fs)
        engines = self._code_engines
        chosen = self._engine or None

        def work() -> dict[str, Any]:
            try:
                item = detection.result()
                if item is None:
                    return self._menu_info([], [], None, chosen)
                formats = item.formats
                recipes = (
                    self._actions.recipes(formats[0], item.ctx)
                    if formats and engines != frozenset()
                    else []
                )
                # Only the engines code_snippet names, if it names some.
                if engines is not None:
                    recipes = [r for r in recipes if _recipe_engine(r) in engines]
                return self._menu_info(formats, recipes, item.ctx, chosen)
            except Exception as exc:
                return {"error": error_text(exc)}

        reply = partial(self._reply, content)
        self._loader.submit(work, reply, reply)

    def _view_entries(
        self, fmt: DataFormat, key: str | None, views: list[ViewAction]
    ) -> list[dict[str, Any]]:
        """The entries of "Preview as" for an item viewed as ``fmt`` with the
        engine of ``key`` by its ``views``: one, e.g. "CSV (Polars)"; or, for
        several, one per view, by its id, labelled with its label, e.g.
        "View as CSV (Polars)" and "CSV in a widget (Polars)"."""
        if len(views) <= 1:
            engine = f"({self._engine_label(key)})" if key else ""
            label = " ".join(filter(None, [fmt.label, engine]))
            return [{"format": fmt.name, "engine": key, "label": label}]
        return [
            {"format": fmt.name, "engine": key, "action": v.id, "label": v.label}
            for v in views
        ]

    def _menu_info(
        self,
        formats: list[DataFormat],
        recipes: list[Recipe],
        ctx: ItemContext | None,
        chosen: str | None,
    ) -> dict[str, Any]:
        """The reply to "menu_info" for the item of ``ctx`` matching
        ``formats``, best first, with ``recipes`` the best format's, and
        ``chosen`` the engine chosen: "formats", the names of those matching;
        "view", the best format and the engine viewing it ("Preview", "View
        in a new tab"; None if the engine chosen cannot); "views", each
        format and engine that can ("Preview as", "View in new tab as"),
        each of the engine's views by name if it has several;
        "recipes", the load code ("Python code"), with their engine's label,
        or the error of an action's. Safe in a worker thread."""
        # A view of a format the item also matches is listed under that
        # format only, e.g. the Text view of a Markdown file under Text, not
        # under Markdown too (a view does its format's subclasses).
        matched = {type(f) for f in formats}

        def own(f: DataFormat, views: list[ViewAction]) -> list[ViewAction]:
            return [v for v in views if v.format is type(f) or v.format not in matched]

        default_view = None
        if formats and ctx is not None:
            try:
                key = self._actions.engine_for(formats[0], ctx, chosen)
            except LookupError:
                pass
            else:
                default_view = {"format": formats[0].name, "engine": key}
        return {
            "formats": [f.name for f in formats],
            "view": default_view,
            "views": [
                entry
                for f in formats
                if ctx is not None
                for key, views in self._actions.views_by_engine(f, ctx).items()
                if (shown := own(f, views))
                for entry in self._view_entries(f, key, shown)
            ],
            # The frontend gets the packages' names, listed under the code.
            "recipes": [
                {
                    "title": r.title,
                    "engine": r.engine.label if r.engine is not None else "Python",
                    "packages": [p.package for p in r.requirements],
                    "code": r.code,
                    **({"error": r.error} if r.error else {}),
                }
                for r in recipes
            ],
        }
