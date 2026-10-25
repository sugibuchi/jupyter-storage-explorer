"""Actions of the user's own, from files: ``storage-explorer/actions.py`` and
``storage-explorer/actions/*.py`` in Jupyter's configuration directories
(``jupyter --paths``, config section), which every explorer loads, in
notebooks, the launcher's tabs and the side panel alike.

The user's directory comes first, then the environment's and the system's;
in each, ``actions.py``, then the folder's files by name, but those whose
names start with "_". A file gives the actions defined at its top level, in
order, or its ``ACTIONS``, a sequence of actions, if it has one (e.g.
``register_actions(...)``, to order them or leave some out). A file that
cannot be imported, gives something else, or whose actions cannot be used
with those before it (e.g. two of one label) is left out, with its reason:
a broken file must not keep the explorer from opening.

The user's ``actions.py`` can be created from ``actions_template.py`` and
opened from the explorer's settings menu (see ``user_actions_file``)."""

from __future__ import annotations

import hashlib
import importlib.resources
import importlib.util
import pathlib
import sys
import warnings
from typing import TYPE_CHECKING, Any

from jupyter_core.paths import jupyter_config_dir, jupyter_config_path

from jupyter_storage_explorer.formats.actions import Action, check_actions

if TYPE_CHECKING:
    from collections.abc import Sequence

# Looked for in each Jupyter configuration directory: a file, then a folder.
USER_ACTIONS_FILE = pathlib.Path("storage-explorer", "actions.py")
USER_ACTIONS_DIR = pathlib.Path("storage-explorer", "actions")


def action_files() -> list[pathlib.Path]:
    """The user's action files, in the order their actions are tried."""
    files: list[pathlib.Path] = []
    for directory in jupyter_config_path():
        single = pathlib.Path(directory) / USER_ACTIONS_FILE
        if single.is_file():
            files.append(single)
        folder = pathlib.Path(directory) / USER_ACTIONS_DIR
        if folder.is_dir():
            files += sorted(
                p
                for p in folder.glob("*.py")
                if p.is_file() and not p.name.startswith("_")
            )
    return files


def user_actions_file() -> pathlib.Path:
    """The user's own ``actions.py``, in the user's Jupyter configuration
    directory (``~/.jupyter``), which the settings menu opens."""
    return pathlib.Path(jupyter_config_dir()) / USER_ACTIONS_FILE


def create_user_actions_file() -> None:
    """Create the user's ``actions.py`` from ``actions_template.py``, if it is
    missing; it gives no action until the user writes some."""
    path = user_actions_file()
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    template = importlib.resources.files("jupyter_storage_explorer").joinpath(
        "actions_template.py"
    )
    path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def load_user_actions(
    others: Sequence[Action[Any]] = (),
) -> tuple[list[Action[Any]], list[str]]:
    """The actions of the user's files (see the module docstring), and why
    some files were left out. ``others`` are the explorer's other actions,
    which a file's must be usable with too."""
    # What is no action is the chain's error to report, not the files'.
    others = [a for a in others if isinstance(a, Action)]
    actions: list[Action[Any]] = []
    problems: list[str] = []
    for path in action_files():
        try:
            found = _actions_of(_load(path))
            check_actions([*actions, *found, *others])
        except Exception as exc:
            problems.append(
                f"user actions {path} not loaded: {type(exc).__name__}: {exc}"
            )
            continue
        actions += found
    return actions, problems


def users_actions_warned(others: Sequence[Action[Any]]) -> list[Action[Any]]:
    """``load_user_actions(others)``'s actions, its problems as warnings
    pointing at the code creating the explorer."""
    actions, problems = load_user_actions(others)
    for problem in problems:
        warnings.warn(problem, RuntimeWarning, stacklevel=3)
    return actions


def _load(path: pathlib.Path) -> Any:
    """Import ``path`` as a module of its own, registered (as dataclasses and
    type hints look modules up) under a name unique to the file."""
    digest = hashlib.sha1(str(path).encode(), usedforsecurity=False).hexdigest()[:12]
    name = f"jupyter_storage_explorer_user_actions_{digest}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _actions_of(module: Any) -> list[Action[Any]]:
    """A file's actions: its ``ACTIONS``, else those defined at its top
    level, in order; not those it imports, e.g. a plugin's."""
    given = getattr(module, "ACTIONS", None)
    if given is not None:
        if isinstance(given, (str, bytes)) or not all(
            isinstance(a, Action) for a in given
        ):
            raise TypeError("ACTIONS must be a sequence of actions")
        return list(given)
    return [
        value
        for value in vars(module).values()
        if isinstance(value, Action)
        and getattr(value.function, "__module__", None) == module.__name__
    ]
