"""Opening Storage Explorer from the JupyterLab launcher, configured in layers.

The "Storage Explorer" item in the launcher opens a new tab with a fresh
kernel, started in the launcher's folder (the one JupyterLab's file browser
showed), which runs ``launch()``; it runs again when the page is reloaded,
and in the new kernel the tab gets after a server or kernel restart, with
the storage and folders it showed.

What the tab shows is configured by files in Jupyter's configuration
directories (``jupyter --paths``, config section): ``storage-explorer/common.py``,
which configures every explorer, and ``storage-explorer/launcher.py``, which
configures the launcher's only. In each directory, launcher.py overrides
common.py. The explorer's ``_extensions/config.py`` describes the layers and
the functions the files may have. For the launcher:

- Without ``filesystems()``, the tab browses the folder it opens on (``"."``).
- ``parameters()``' ``height`` is ``"fill"`` unless set, and ``states``
  (bookmarks and recent queries) the file ``storage-explorer/states.json``
  in the user's Jupyter configuration directory, shared by the tabs
  (``None``: in each tab's memory only).
- The side panel's explorer has the same settings, but its own ``height``,
  ``tree_view``, ``preview_panel`` and ``layout`` (``SIDEBAR``).

For example, ``/etc/jupyter/storage-explorer/launcher.py``::

    def filesystems():
        return {"Data lake": "abfs://lake@myaccount.dfs.core.windows.net"}

    def transfer_policy():
        # Nothing leaves the lake for users' computers.
        return [{"rule": "deny", "src": "abfs://lake@.*", "dest": "browser:///.*"}]

    def final():
        # Users cannot change the storages offered, or the policy.
        return ["filesystems", "transfer_policy"]

and ``~/.jupyter/storage-explorer/launcher.py``::

    def parameters():
        return {"max_browser_items": 50_000}

The tab's settings button (in its toolbar) opens the user's launcher.py in
JupyterLab's editor, created from ``launcher_template.py`` if it is missing.

The user's files with an error are left out, with a warning: the tab opens
without them, so that the user can fix them. The explorer is also created
again without them if it cannot be with them (e.g. a parameter's value it
refuses). An error in another file, an administrator's, stops the tab, which
then shows the error only.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib.resources
import json
import logging
import pathlib
import sys
from typing import TYPE_CHECKING, Any

from jupyter_core.paths import jupyter_config_dir

from jupyter_storage_explorer._extensions.config import (
    COMMON_FILE,
    LAUNCHER_FILE,
    MERGES,
    ConfigError,
    Settings,
    find_config_files,
    same_file,
    user_common_file,
)
from jupyter_storage_explorer._extensions.config import (
    load_settings as load_layers,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# Under the explorer's logger, whose level and files the Logging menu sets.
log = logging.getLogger("jupyter_storage_explorer.launcher")


@dataclasses.dataclass
class LauncherSettings(Settings):
    """The settings of all the layers, merged, for the launcher's explorers."""

    def explorer_arguments(
        self, sidebar: bool = False
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """The positional and keyword arguments to create the explorer with;
        ``sidebar``: for the side panel, whose layout ``SIDEBAR`` sets over
        the parameters."""
        kwargs: dict[str, Any] = {
            "height": "fill",
            "states": states_file(),
            # The user's actions files configure JupyterLab's explorers, the
            # launcher's: explorers in notebooks read none by default.
            "user_actions": "enabled",
            # The launcher's explorers log to files, once the user chooses a
            # level in their Logging menu; explorers in notebooks, to the
            # console.
            "logging_menu": "enabled",
            "logging_level": "disabled",
            **self.parameters,
            **(SIDEBAR if sidebar else {}),
            # The common.py files are among these settings' layers.
            "common_config": "disabled",
        }
        # The functions' values, as the explorer's arguments of their names:
        # lists copied, so that the explorer never changes the settings.
        for name in MERGES:
            value = getattr(self, name)
            if name != "filesystems" and value:
                kwargs[name] = list(value) if isinstance(value, list) else value
        if filesystems := self.shown_filesystems:
            return (), {"filesystems": filesystems, **kwargs}
        return (".",), kwargs

    def create_widget(self, sidebar: bool = False) -> Any:
        """The explorer these settings describe (for the side panel with
        ``sidebar``)."""
        from jupyter_storage_explorer import StorageExplorer  # noqa: PLC0415

        args, kwargs = self.explorer_arguments(sidebar)
        if "states" not in self.parameters:
            states_file().parent.mkdir(parents=True, exist_ok=True)
        return StorageExplorer(*args, **kwargs)


# The side panel's explorer, whatever the parameters: narrow, filling the
# panel, without the tree or the preview panel (items open in new tabs).
SIDEBAR = {
    "height": "fill",
    "tree_view": "disabled",
    "preview_panel": "disabled",
    "layout": "sidebar",
}


def states_file() -> pathlib.Path:
    """Where the tabs keep their bookmarks and recent queries, unless
    ``parameters()`` sets ``states``: in the user's Jupyter configuration
    directory (``~/.jupyter`` unless ``JUPYTER_CONFIG_DIR`` is set), beside
    their ``storage-explorer/launcher.py``."""
    return pathlib.Path(jupyter_config_dir(), "storage-explorer", "states.json")


def user_launcher_file() -> pathlib.Path:
    """The user's launcher.py, in their Jupyter configuration directory
    (``~/.jupyter`` unless ``JUPYTER_CONFIG_DIR`` is set), which the tab's
    settings button opens; it may not exist yet."""
    return pathlib.Path(jupyter_config_dir(), LAUNCHER_FILE)


def user_files() -> list[pathlib.Path]:
    """The user's files, left out if they have an error."""
    return [user_launcher_file(), user_common_file()]


def create_user_launcher_file() -> pathlib.Path:
    """``user_launcher_file()``, created from the template (every function
    commented out but an empty ``filesystems()``, so it changes nothing) if
    it is missing; an existing file is left as it is."""
    path = user_launcher_file()
    if not path.exists():
        template = importlib.resources.files(__package__).joinpath(
            "launcher_template.py"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # "x": never over a file created meanwhile, e.g. by another tab.
        with (
            contextlib.suppress(FileExistsError),
            path.open("x", encoding="utf-8") as f,
        ):
            f.write(template.read_text(encoding="utf-8"))
    return path


def find_launcher_files() -> list[pathlib.Path]:
    """The launcher.py and common.py files, in Jupyter's order: the user's
    first, the system's last; in each directory, launcher.py first, as it
    overrides common.py."""
    return find_config_files([LAUNCHER_FILE, COMMON_FILE])


def load_settings(
    files: Sequence[pathlib.Path] | None = None,
    *,
    user: Sequence[pathlib.Path] | None = None,
) -> LauncherSettings:
    """Merge the settings of ``files`` (default: ``find_launcher_files()``),
    applied from the last (the system's) to the first (the user's).

    Raises ConfigError if a file cannot be used, except the user's files,
    ``user`` (default: ``user_files()``): they are left out instead, with
    their errors in ``Settings.user_errors``, so that the tab still opens and
    the user can fix them.
    """
    settings = LauncherSettings()
    load_layers(
        find_launcher_files() if files is None else files,
        user_files=user_files() if user is None else user,
        into=settings,
    )
    return settings


@dataclasses.dataclass
class _Launched:
    """An explorer ``launch()`` showed in this kernel, with what it was made
    from: the files' fingerprint, and the warnings shown above it."""

    explorer: Any
    fingerprint: str
    warnings: list[str]


# The explorers launch() showed in this kernel, by kind: the side panel's
# (True) or a tab's (False); each has a kernel of its own. A page reload runs
# launch() again in the same kernel (see the extension's index.ts), which
# shows the same explorer again, as it was, unless the files changed.
_launched: dict[bool, _Launched] = {}


def launch(view: str | None = None, sidebar: bool = False) -> None:
    """Run by the launcher's tab or side panel: show the layers' warnings,
    and the explorer.

    ``view``: the tab's view when it was last open, as JSON ({"filesystem":
    name, "folders": {name: folder}}), saved by the tab (see the extension's
    index.ts): the explorer reopens there. A view that cannot be used is
    ignored. ``sidebar``: the explorer of the side panel (``SIDEBAR``).

    Run again in the same kernel, after a page reload, it shows the explorer
    it made before, as it was (its folder, selection, preview), unless the
    files have changed since: those apply then, in a new one.
    """
    from IPython.display import display  # noqa: PLC0415

    files = find_launcher_files()
    fingerprint = _fingerprint(files)
    previous = _launched.pop(sidebar, None)
    if previous is not None:
        if previous.fingerprint == fingerprint and _open(previous.explorer):
            # Its tabs went with the page: their views are released.
            previous.explorer._release_view_tabs()
            for warning in previous.warnings:
                print(warning, file=sys.stderr)
            display(previous.explorer)
            _launched[sidebar] = previous
            log.info("The %s's explorer shown again", _place(sidebar))
            return
        log.info(
            "The configuration files changed: the %s's explorer made again",
            _place(sidebar),
        )
        previous.explorer.close()
    try:
        settings = load_settings(files)
        explorer = _create_explorer(settings, view, sidebar)
    except ConfigError as exc:
        # In a system file, or the explorer cannot be created even without
        # the user's: the tab cannot open. Said plainly, not as a traceback.
        print(f"Storage Explorer cannot open: {exc}", file=sys.stderr)
        return
    warnings = list(settings.warnings)
    warnings += [_left_out(error) for error in settings.user_errors]
    for warning in warnings:
        print(warning, file=sys.stderr)
    # Logged once the explorer is made, which sets up the kernel's logging:
    # before, records would go to stderr, shown in the tab a second time.
    # Not the failures above, for that reason.
    log.info(
        "The %s opened with the settings of %s",
        _place(sidebar),
        ", ".join(str(path) for path in settings.files) or "no configuration file",
    )
    for warning in warnings:
        log.warning("%s", warning)
    display(explorer)
    _launched[sidebar] = _Launched(explorer, fingerprint, warnings)


def _place(sidebar: bool) -> str:
    """Where the explorer shows, for the logs."""
    return "side panel" if sidebar else "tab"


def _fingerprint(files: Sequence[pathlib.Path]) -> str:
    """What the configuration ``files`` hold: their paths and contents, so
    that a change to any, or a file added or removed, gives another."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path).encode())
        with contextlib.suppress(OSError):
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _open(explorer: Any) -> bool:
    """Whether ``explorer`` can still be shown: not closed (its comm gone)."""
    return getattr(explorer, "comm", None) is not None


def _left_out(error: str) -> str:
    """The warning of a user's file left out because of ``error``."""
    return (
        f"Your settings were left out: {error}. Fix them with the settings "
        f"button in the toolbar, then open the tab again."
    )


def _create_explorer(
    settings: LauncherSettings, view: str | None, sidebar: bool = False
) -> Any:
    """The explorer ``settings`` describe, showing ``view`` (see ``launch``).

    If it cannot be created with them, e.g. for a parameter's value, it is
    created again without the user's files, whose error then goes in
    ``settings.user_errors``; ConfigError if it still cannot be."""
    try:
        explorer = settings.create_widget(sidebar)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        user = user_files()
        mine = [p for p in settings.files if any(same_file(p, u) for u in user)]
        if not mine:
            raise ConfigError(f"the explorer cannot be created: {error}") from exc
        others = [path for path in settings.files if path not in mine]
        # Applied from the last: back in Jupyter's order, the user's first.
        without = load_settings(others[::-1], user=user)
        try:
            explorer = without.create_widget(sidebar)
        except Exception as again:
            raise ConfigError(
                f"the explorer cannot be created: {type(again).__name__}: {again}"
            ) from again
        # The settings the explorer has, for the warnings launch() shows,
        # with the user's files left out before.
        errors = settings.user_errors
        settings.__dict__.update(without.__dict__)
        names = ", ".join(str(path) for path in mine)
        settings.user_errors = [
            *errors,
            f"{names}: the explorer cannot be created with them: {error}",
        ]
    explorer._offer_config_file(
        "launcher", user_launcher_file(), create_user_launcher_file
    )
    if settings.user_errors:
        # Also in the explorer, until it lists another folder.
        explorer._error = _left_out(settings.user_errors[-1])
    if view:
        # Else (e.g. a storage unreachable now) the explorer as it starts.
        with contextlib.suppress(Exception):
            saved = json.loads(view)
            explorer._restore_view(saved.get("filesystem"), saved.get("folders"))
    return explorer
