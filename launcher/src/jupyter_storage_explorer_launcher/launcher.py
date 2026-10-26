"""Opening Storage Explorer from the JupyterLab launcher, configured in layers.

The "Storage Explorer" item in the launcher opens a new tab with a fresh
kernel, started in the launcher's folder (the one JupyterLab's file browser
showed), which runs ``launch()``; it runs again when the page is reloaded,
and in the new kernel the tab gets after a server or kernel restart, with
the storage and folders it showed.

What the tab shows is configured by files ``storage-explorer/launcher.py`` in
Jupyter's configuration directories (``jupyter --paths``, config section:
e.g. ``~/.jupyter`` for the user, ``<env>/etc/jupyter`` for the
environment, ``/usr/local/etc/jupyter`` and ``/etc/jupyter`` for the
system). Every file found is a layer: they are applied from the last
directory (the system's) to the first (usually the user's; in a virtual
environment, Jupyter searches the environment's first), each adding to or
overriding the settings of those before, except the settings they made
final. Each file may have these functions, all optional:

``filesystems()``
    ``{name: URL or fsspec filesystem}``, merged by name: a later layer adds
    entries or replaces them, and removes them with ``None``. Without any,
    the tab browses the folder it opens on (``"."``).
``plugin_options()``
    ``{plugin key: {option: value}}`` (see ``StorageExplorer``'s
    ``plugin_options``), e.g. ``{"pandas-support": {"enabled": False}}``,
    merged by plugin, then option. Every plugin installed is used unless
    disabled.
``actions()``
    ``[action, ...]``: what explorers do with formats' data, functions of
    your own decorated with ``actions.view`` or ``code``, tried
    after the plugins' and the explorer's own, as additions offered in its
    menus; a later layer's come first. Their formats are detected with the
    defaults'. Two actions of one kind, format, engine and label stop the
    tab with an error: give yours another label.
``engine_options()``
    ``{engine key: {format or "*": {option: value}}}`` for the actions (see
    ``StorageExplorer``'s ``engine_options``), merged option by option (a
    value is replaced whole, e.g. a ``storage_options`` dict). Options may
    be a function of the item's location returning them: merged with
    another layer's, the later layer's options still win option by option.
``operations()``
    ``[FileSystemOperations, ...]``: file operations of your own, tried
    before ``StorageExplorer.default_operations()``; a later layer's come
    first.
``filesystem_mappers()``
    ``[FileSystemMapper, ...]``: how filesystems of your own are told apart
    and their paths become URLs (see ``jupyter_storage_explorer.filesystems``),
    tried before the defaults; a later layer's come first.
``transfer_policy()``
    ``[{"rule": "allow" or "deny", "src": regex, "dest": regex}, ...]``:
    the rules of the directions files may be transferred in (see
    ``StorageExplorer``'s ``transfer_policy``); a later layer's come first,
    so they decide before an earlier layer's, unless one made the policy
    final.
``parameters()``
    ``{parameter: value}`` for ``StorageExplorer``'s other arguments, e.g.
    ``{"height": "fill", "max_upload_bytes": None}``, merged by name.
    ``height`` is ``"fill"`` unless set, and ``states`` (bookmarks and
    recent queries) the file ``storage-explorer/states.json`` in the user's
    Jupyter configuration directory, shared by the tabs (``None``: in each
    tab's memory only). The side panel's explorer has the same settings,
    but its own ``height``, ``tree_view``, ``preview_panel`` and ``layout``
    (``SIDEBAR``).
``final()``
    ``["filesystems", "height", ...]``: settings later layers cannot change:
    the names of the functions above, except ``parameters``, and the names
    of parameters. A later layer's attempt is ignored, with a warning shown
    in the tab. This is a convenience for administrators, not a security
    boundary: users can always create explorers of their own in notebooks.

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

The tab's settings button (in its toolbar) opens the user's file in
JupyterLab's editor, created from ``launcher_template.py`` if it is missing.

A user's file with an error is left out, with a warning: the tab opens
without it, so that the user can fix it with that button. The explorer is
also created again without it if it cannot be with it (e.g. a parameter's
value it refuses). An error in another file, an administrator's, stops the
tab, which then shows the error only.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib.resources
import importlib.util
import inspect
import json
import pathlib
import sys
from typing import TYPE_CHECKING, Any

from jupyter_core.paths import jupyter_config_dir, jupyter_config_path

if TYPE_CHECKING:
    from collections.abc import Sequence

# Looked for in each Jupyter configuration directory.
LAUNCHER_FILE = pathlib.Path("storage-explorer", "launcher.py")

# The functions a launcher.py may have, besides final().
HOOKS = (
    "filesystems",
    "plugin_options",
    "actions",
    "engine_options",
    "operations",
    "filesystem_mappers",
    "transfer_policy",
    "parameters",
)

# Former names of functions, taken for the new ones, also in final(). To be
# removed in the major release.
ALIASES = {"format_options": "engine_options"}

# Functions launcher.py files may still have, no longer used: they are
# ignored (and their names in final()), with a warning shown in the tab.
RETIRED = {
    # CSS applied to the page while the tab was open: not to explorers in
    # notebooks, which JupyterLab's custom.css reaches.
    "style": "use JupyterLab's custom.css instead, for every page (see Icons in the project's DEVELOPMENT.md)",
    # Formats are those of the actions.
    "formats": "give actions() of your formats instead: explorers detect their formats",
    # FormatSupport classes, replaced by actions.
    "supports": "give actions() instead: functions decorated with @view or @code (see the plugin guide)",
}

# StorageExplorer arguments that are not "parameters": set by their own
# function, or by the launcher.
_NOT_PARAMETERS = frozenset(
    {
        "self",
        "path",
        "fs",
        "filesystems",
        "plugin_options",
        "actions",
        "engine_options",
        # engine_options' former name (see ALIASES).
        "format_options",
        "operations",
        "filesystem_mappers",
        "transfer_policy",
    }
)


class LauncherError(Exception):
    """A launcher.py that cannot be used: the message names it."""


@dataclasses.dataclass
class Settings:
    """The settings of all the layers, merged (see the module docstring).

    ``warnings`` are the changes ignored because an earlier layer made the
    setting final, and the functions no longer used (see ``RETIRED``), shown
    in the tab. ``files`` are the layers applied, in the order applied.
    ``user_error`` says why the user's launcher.py was left out, if it was
    (see ``load_settings``).
    """

    filesystems: dict[str, Any] = dataclasses.field(default_factory=dict)
    # {plugin key: {option: value}}
    plugin_options: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    actions: list[Any] = dataclasses.field(default_factory=list)
    # {engine key: {format or "*": a dict of options, or a function of the location}}
    engine_options: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    operations: list[Any] = dataclasses.field(default_factory=list)
    filesystem_mappers: list[Any] = dataclasses.field(default_factory=list)
    transfer_policy: list[Any] = dataclasses.field(default_factory=list)
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    warnings: list[str] = dataclasses.field(default_factory=list)
    files: list[pathlib.Path] = dataclasses.field(default_factory=list)
    user_error: str = ""

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
            **self.parameters,
            **(SIDEBAR if sidebar else {}),
        }
        if self.plugin_options:
            kwargs["plugin_options"] = self.plugin_options
        if self.actions:
            kwargs["actions"] = list(self.actions)
        if self.engine_options:
            kwargs["engine_options"] = self.engine_options
        if self.operations:
            kwargs["operations"] = list(self.operations)
        if self.filesystem_mappers:
            kwargs["filesystem_mappers"] = list(self.filesystem_mappers)
        if self.transfer_policy:
            kwargs["transfer_policy"] = list(self.transfer_policy)
        filesystems = {k: v for k, v in self.filesystems.items() if v is not None}
        if filesystems:
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
    """The launcher.py files, in Jupyter's order: the user's first, the system's last."""
    files = []
    for directory in jupyter_config_path():
        path = pathlib.Path(directory) / LAUNCHER_FILE
        if path.is_file() and path not in files:
            files.append(path)
    return files


def load_settings(
    files: Sequence[pathlib.Path] | None = None,
    *,
    user_file: pathlib.Path | None = None,
) -> Settings:
    """Merge the settings of ``files`` (default: ``find_launcher_files()``),
    applied from the last (the system's) to the first (the user's).

    Raises LauncherError if a file cannot be loaded, a function fails, or
    returns names that do not exist. Except the user's file, ``user_file``
    (default: ``user_launcher_file()``): it is left out instead, with its
    error in ``Settings.user_error``, so that the tab still opens and the
    user can fix it with the settings button.
    """
    files = find_launcher_files() if files is None else list(files)
    user_file = user_launcher_file() if user_file is None else user_file
    settings = Settings()
    # Name -> the file that made it final.
    final: dict[str, pathlib.Path] = {}
    for path in reversed(files):
        try:
            values, warnings = _read_layer(path)
            _check_layer(values, path, final)
        except LauncherError as exc:
            if not _same_file(path, user_file):
                raise
            settings.user_error = str(exc)
            continue
        settings.warnings += warnings
        _apply(settings, values, path, final)
        for name in values["final"] or ():
            if name not in RETIRED:  # its function is ignored anyway
                final.setdefault(name, path)
        settings.files.append(path)
    return settings


def _read_layer(path: pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    """What the functions of launcher.py ``path`` return, by name, and the
    warnings of the functions no longer used. LauncherError if it cannot be
    loaded, or a function fails."""
    module = _load(path)
    warnings = []
    if callable(getattr(module, "launch", None)):
        # The launcher's configuration before 0.6.0: now ignored.
        warnings.append(
            f"{path}: launch() is no longer used; set filesystems(), "
            f"parameters() etc. instead (see the launcher's README)"
        )
    for name, instead in RETIRED.items():
        if callable(getattr(module, name, None)):
            warnings.append(
                f"{path}: {name}() is no longer used and is ignored; {instead}"
            )
    values = {name: _call(module, path, name) for name in (*HOOKS, "final")}
    for old, new in ALIASES.items():
        value = _call(module, path, old)
        if value is not None:
            if values[new] is not None:
                raise LauncherError(
                    f"{path}: give {new}() only: {old}() is its former name"
                )
            values[new] = value
    if values["final"]:
        values["final"] = [ALIASES.get(name, name) for name in values["final"]]
    return values, warnings


def _check_layer(
    values: dict[str, Any], path: pathlib.Path, final: dict[str, pathlib.Path]
) -> None:
    """LauncherError if a layer's ``values`` cannot be applied: checked before
    applying them, so that a layer with an error leaves the settings as they
    were. Its checks are those of ``_apply`` (applied to settings of their own
    here), and the names given to ``final()``."""
    _apply(Settings(), values, path, dict(final))
    for name in values["final"] or ():
        if name not in RETIRED:
            _check_final_name(name, path)


def _same_file(path: pathlib.Path, other: pathlib.Path) -> bool:
    try:
        return path.resolve() == other.resolve()
    except OSError:
        return path == other


def _apply(
    settings: Settings,
    values: dict[str, Any],
    path: pathlib.Path,
    final: dict[str, pathlib.Path],
) -> None:
    """Merge one layer's ``values`` into ``settings``, except what is ``final``."""
    for name, merge in _MERGES.items():
        value = values[name]
        if value is None or not _allowed(settings, final, path, name):
            continue
        if merge == "by name":
            getattr(settings, name).update(_mapping(value, path, name))
        elif merge == "by option":
            _merge_engine_options(settings.engine_options, value, path)
        elif merge == "by plugin":
            _merge_plugin_options(settings.plugin_options, value, path)
        else:  # "first"
            getattr(settings, name)[:0] = _sequence(value, path, name)
    if values["parameters"] is not None:
        for name, value in _mapping(values["parameters"], path, "parameters").items():
            _check_parameter_name(name, path)
            if _allowed(settings, final, path, name):
                settings.parameters[name] = value


def _allowed(
    settings: Settings,
    final: dict[str, pathlib.Path],
    path: pathlib.Path,
    name: str,
) -> bool:
    """Whether ``path`` may set ``name``; if not (it is final), warn."""
    if name not in final:
        return True
    settings.warnings.append(f"{path}: {name} is ignored: it is final in {final[name]}")
    return False


# How each function's values are merged with those of earlier layers (see the
# module docstring); parameters() is merged parameter by parameter.
_MERGES = {
    "filesystems": "by name",
    "plugin_options": "by plugin",
    "actions": "first",
    "engine_options": "by option",
    "operations": "first",
    "filesystem_mappers": "first",
    "transfer_policy": "first",
}


def _load(path: pathlib.Path) -> Any:
    """Import ``path`` as a module of its own."""
    spec = importlib.util.spec_from_file_location(
        f"storage_explorer_launcher_{abs(hash(str(path)))}", path
    )
    if spec is None or spec.loader is None:
        raise LauncherError(f"{path}: cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LauncherError(f"{path}: {type(exc).__name__}: {exc}") from exc
    return module


def _call(module: Any, path: pathlib.Path, name: str) -> Any:
    """What ``module``'s function ``name`` returns; None if it has none."""
    function = getattr(module, name, None)
    if function is None:
        return None
    if not callable(function):
        raise LauncherError(f"{path}: {name} must be a function")
    try:
        return function()
    except Exception as exc:
        raise LauncherError(f"{path}: {name}(): {type(exc).__name__}: {exc}") from exc


def _merge_plugin_options(
    merged: dict[str, dict[str, Any]], value: Any, path: pathlib.Path
) -> None:
    """Merge one layer's ``plugin_options()`` into ``merged``: by plugin, then
    option, so a layer disables a plugin, or changes one option of it,
    without restating the others. Whether they exist is checked by the
    explorer."""
    for key, options in _mapping(value, path, "plugin_options").items():
        if not isinstance(options, dict):
            raise LauncherError(
                f"{path}: plugin_options(): {key!r} must map option names to values"
            )
        merged.setdefault(key, {}).update(options)


def _mapping(value: Any, path: pathlib.Path, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LauncherError(f"{path}: {name}() must return a dict")
    return value


def _merge_engine_options(
    merged: dict[str, dict[str, Any]], value: Any, path: pathlib.Path
) -> None:
    """Merge one layer's ``engine_options()`` into ``merged``: by engine,
    format, then option, so a layer changes one option of a format without
    restating the others. Whether the names exist is checked by the explorer."""
    for library, by_format in _mapping(value, path, "engine_options").items():
        if not isinstance(by_format, dict) or not all(
            isinstance(options, dict) or callable(options)
            for options in by_format.values()
        ):
            raise LauncherError(
                f"{path}: engine_options(): {library!r} must map format names "
                f'(or "*") to dicts of options, or functions of the location '
                f"returning them"
            )
        formats = merged.setdefault(library, {})
        for name, options in by_format.items():
            formats[name] = _merged_options(formats.get(name), options)


def _merged_options(earlier: Any, later: Any) -> Any:
    """A later layer's options of a format over an earlier layer's, option by
    option: a dict while both are dicts, else a function of the location
    (as either may be) giving the earlier's options updated with the
    later's."""
    if earlier is None:
        return dict(later) if isinstance(later, dict) else later
    if isinstance(earlier, dict) and isinstance(later, dict):
        return {**earlier, **later}

    def options(location: Any) -> dict[str, Any]:
        return {**_options_at(earlier, location), **_options_at(later, location)}

    return options


def _options_at(options: Any, location: Any) -> dict[str, Any]:
    """``options``, or what the function ``options`` gives for ``location``."""
    return dict(options(location) if callable(options) else options)


def _sequence(value: Any, path: pathlib.Path, name: str) -> list[Any]:
    if isinstance(value, (str, bytes, dict)) or not hasattr(value, "__iter__"):
        raise LauncherError(f"{path}: {name}() must return a list")
    return list(value)


def _parameter_names() -> frozenset[str]:
    """``StorageExplorer``'s arguments that ``parameters()`` may set."""
    from jupyter_storage_explorer import StorageExplorer  # noqa: PLC0415

    parameters = inspect.signature(StorageExplorer.__init__).parameters
    return frozenset(
        name
        for name, p in parameters.items()
        if name not in _NOT_PARAMETERS and p.kind is not p.VAR_KEYWORD
    )


def _check_parameter_name(name: str, path: pathlib.Path) -> None:
    if name in _NOT_PARAMETERS - {"self"}:
        raise LauncherError(
            f"{path}: parameters(): {name} is set by its own function, not parameters()"
            if name in HOOKS or name in ALIASES
            else f"{path}: parameters(): {name} is set by the launcher (use filesystems())"
        )
    if name not in _parameter_names():
        raise LauncherError(f"{path}: parameters(): unknown parameter {name!r}")


def _check_final_name(name: str, path: pathlib.Path) -> None:
    if name in HOOKS and name != "parameters":
        return
    if name not in _parameter_names():
        raise LauncherError(
            f"{path}: final(): unknown setting {name!r} (a function name other "
            f"than parameters, or a parameter name)"
        )


def create_widget(sidebar: bool = False) -> Any:
    """The explorer the launcher.py files describe (see the module docstring);
    with ``sidebar``, the side panel's (``SIDEBAR``)."""
    return load_settings().create_widget(sidebar)


@dataclasses.dataclass
class _Launched:
    """An explorer ``launch()`` showed in this kernel, with what it was made
    from: the launcher.py files' fingerprint, and the warnings shown above it."""

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
    launcher.py files have changed since: those apply then, in a new one.
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
            return
        previous.explorer.close()
    try:
        settings = load_settings(files)
        explorer = _create_explorer(settings, view, sidebar)
    except LauncherError as exc:
        # In a system file, or the explorer cannot be created even without
        # the user's: the tab cannot open. Said plainly, not as a traceback.
        print(f"Storage Explorer cannot open: {exc}", file=sys.stderr)
        return
    warnings = list(settings.warnings)
    if settings.user_error:
        warnings.append(_left_out(settings.user_error))
    for warning in warnings:
        print(warning, file=sys.stderr)
    display(explorer)
    _launched[sidebar] = _Launched(explorer, fingerprint, warnings)


def _fingerprint(files: Sequence[pathlib.Path]) -> str:
    """What launcher.py ``files`` hold: their paths and contents, so that a
    change to any, or a file added or removed, gives another."""
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
    """The warning of a user's launcher.py left out because of ``error``."""
    return (
        f"Your launcher settings were left out: {error}. Fix them with the "
        f"settings button in the toolbar, then open the tab again."
    )


def _create_explorer(
    settings: Settings, view: str | None, sidebar: bool = False
) -> Any:
    """The explorer ``settings`` describe, showing ``view`` (see ``launch``).

    If it cannot be created with them, e.g. for a parameter's value, it is
    created again without the user's launcher.py, whose error then goes in
    ``settings.user_error``; LauncherError if it still cannot be."""
    try:
        explorer = settings.create_widget(sidebar)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        user = user_launcher_file()
        if not any(_same_file(path, user) for path in settings.files):
            raise LauncherError(f"the explorer cannot be created: {error}") from exc
        others = [path for path in settings.files if not _same_file(path, user)]
        # Applied from the last: back in Jupyter's order, the user's first.
        without = load_settings(others[::-1], user_file=user)
        try:
            explorer = without.create_widget(sidebar)
        except Exception as again:
            raise LauncherError(
                f"the explorer cannot be created: {type(again).__name__}: {again}"
            ) from again
        # The settings the explorer has, for the warnings launch() shows.
        settings.__dict__.update(without.__dict__)
        settings.user_error = f"{user}: the explorer cannot be created with it: {error}"
    explorer._offer_config_file(
        "launcher", user_launcher_file(), create_user_launcher_file
    )
    if settings.user_error:
        # Also in the explorer, until it lists another folder.
        explorer._error = _left_out(settings.user_error)
    if view:
        # Else (e.g. a storage unreachable now) the explorer as it starts.
        with contextlib.suppress(Exception):
            saved = json.loads(view)
            explorer._restore_view(saved.get("filesystem"), saved.get("folders"))
    return explorer
