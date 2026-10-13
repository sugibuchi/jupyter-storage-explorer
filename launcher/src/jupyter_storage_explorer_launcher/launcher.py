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
``formats()``
    ``[DataFormat, ...]``: formats of your own, tried before the defaults;
    a later layer's come first.
``format_options()``
    ``{option: value}`` for the default formats, merged by option name (a
    value is replaced whole, e.g. a ``polars_storage_options`` dict).
``operations()``
    ``[FileSystemOperations, ...]``: file operations of your own, tried
    before ``StorageExplorer.default_operations()``; a later layer's come
    first.
``parameters()``
    ``{parameter: value}`` for ``StorageExplorer``'s other arguments, e.g.
    ``{"height": "fill", "max_upload_bytes": None}``, merged by name.
    ``height`` is ``"fill"`` unless set, and ``states`` (bookmarks and
    recent queries) the file ``storage-explorer/states.json`` in the user's
    Jupyter configuration directory, shared by the tabs (``None``: in each
    tab's memory only).
``style()``
    CSS (without ``<style>``) applied to the page while the tab is open, e.g.
    to customize the explorer's icons; the layers' are joined, the user's
    last.
``final()``
    ``["filesystems", "height", ...]``: settings later layers cannot change:
    the names of the functions above, except ``parameters``, and the names
    of parameters. A later layer's attempt is ignored, with a warning shown
    in the tab. This is a convenience for administrators, not a security
    boundary: users can always create explorers of their own in notebooks.

For example, ``/etc/jupyter/storage-explorer/launcher.py``::

    def filesystems():
        return {"Data lake": "abfs://lake@myaccount.dfs.core.windows.net"}

    def final():
        return ["filesystems"]  # users cannot change the storages offered

and ``~/.jupyter/storage-explorer/launcher.py``::

    def parameters():
        return {"max_browser_items": 50_000}
"""

from __future__ import annotations

import contextlib
import dataclasses
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
    "formats",
    "format_options",
    "operations",
    "parameters",
    "style",
)

# StorageExplorer arguments that are not "parameters": set by their own
# function, or by the launcher.
_NOT_PARAMETERS = frozenset(
    {"self", "path", "fs", "filesystems", "formats", "format_options", "operations"}
)


class LauncherError(Exception):
    """A launcher.py that cannot be used: the message names it."""


@dataclasses.dataclass
class Settings:
    """The settings of all the layers, merged (see the module docstring).

    ``warnings`` are the changes ignored because an earlier layer made the
    setting final, shown in the tab.
    """

    filesystems: dict[str, Any] = dataclasses.field(default_factory=dict)
    formats: list[Any] = dataclasses.field(default_factory=list)
    format_options: dict[str, Any] = dataclasses.field(default_factory=dict)
    operations: list[Any] = dataclasses.field(default_factory=list)
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    style: str = ""
    warnings: list[str] = dataclasses.field(default_factory=list)

    def explorer_arguments(self) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """The positional and keyword arguments to create the explorer with."""
        from jupyter_storage_explorer import StorageExplorer  # noqa: PLC0415
        from jupyter_storage_explorer.formats import default_formats  # noqa: PLC0415

        kwargs: dict[str, Any] = {
            "height": "fill",
            "states": states_file(),
            **self.parameters,
        }
        if self.formats:
            # StorageExplorer takes formats or format_options, not both.
            kwargs["formats"] = [*self.formats, *default_formats(self.format_options)]
        elif self.format_options:
            kwargs["format_options"] = dict(self.format_options)
        if self.operations:
            kwargs["operations"] = [
                *self.operations,
                *StorageExplorer.default_operations(),
            ]
        filesystems = {k: v for k, v in self.filesystems.items() if v is not None}
        if filesystems:
            return (), {"filesystems": filesystems, **kwargs}
        return (".",), kwargs

    def create_widget(self) -> Any:
        """The explorer these settings describe."""
        from jupyter_storage_explorer import StorageExplorer  # noqa: PLC0415

        args, kwargs = self.explorer_arguments()
        if "states" not in self.parameters:
            states_file().parent.mkdir(parents=True, exist_ok=True)
        return StorageExplorer(*args, **kwargs)


def states_file() -> pathlib.Path:
    """Where the tabs keep their bookmarks and recent queries, unless
    ``parameters()`` sets ``states``: in the user's Jupyter configuration
    directory (``~/.jupyter`` unless ``JUPYTER_CONFIG_DIR`` is set), beside
    their ``storage-explorer/launcher.py``."""
    return pathlib.Path(jupyter_config_dir(), "storage-explorer", "states.json")


def find_launcher_files() -> list[pathlib.Path]:
    """The launcher.py files, in Jupyter's order: the user's first, the system's last."""
    files = []
    for directory in jupyter_config_path():
        path = pathlib.Path(directory) / LAUNCHER_FILE
        if path.is_file() and path not in files:
            files.append(path)
    return files


def load_settings(files: Sequence[pathlib.Path] | None = None) -> Settings:
    """Merge the settings of ``files`` (default: ``find_launcher_files()``),
    applied from the last (the system's) to the first (the user's).

    Raises LauncherError if a file cannot be loaded, a function fails, or
    returns names that do not exist.
    """
    files = find_launcher_files() if files is None else list(files)
    settings = Settings()
    # Name -> the file that made it final.
    final: dict[str, pathlib.Path] = {}
    for path in reversed(files):
        module = _load(path)
        if callable(getattr(module, "launch", None)):
            # The launcher's configuration before 0.6.0: now ignored.
            settings.warnings.append(
                f"{path}: launch() is no longer used; set filesystems(), "
                f"parameters() etc. instead (see the launcher's README)"
            )
        values = {name: _call(module, path, name) for name in (*HOOKS, "final")}
        _apply(settings, values, path, final)
        for name in values["final"] or ():
            _check_final_name(name, path)
            final.setdefault(name, path)
    return settings


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
        elif merge == "first":
            getattr(settings, name)[:0] = _sequence(value, path, name)
        elif value:  # "joined": style
            settings.style = "\n".join(s for s in (settings.style, str(value)) if s)
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
    "formats": "first",
    "format_options": "by name",
    "operations": "first",
    "style": "joined",
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


def _mapping(value: Any, path: pathlib.Path, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LauncherError(f"{path}: {name}() must return a dict")
    return value


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
            if name in HOOKS
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


def create_widget() -> Any:
    """The explorer the launcher.py files describe (see the module docstring)."""
    return load_settings().create_widget()


def launch(view: str | None = None) -> None:
    """Run by the launcher's tab: apply the layers' ``style()``, show their
    warnings, and show the explorer.

    ``view``: the tab's view when it was last open, as JSON ({"filesystem":
    name, "folders": {name: folder}}), saved by the tab (see the extension's
    index.ts): the explorer reopens there. A view that cannot be used is
    ignored.
    """
    from IPython.display import HTML, display  # noqa: PLC0415

    settings = load_settings()
    if settings.style:
        # A <style> output applies to the whole page while the tab is open;
        # the tab's CSS hides the (empty) output itself.
        display(HTML(f"<style>{settings.style}</style>"))
    for warning in settings.warnings:
        print(warning, file=sys.stderr)
    display(_create_explorer(settings, view))


def _create_explorer(settings: Settings, view: str | None) -> Any:
    """The explorer ``settings`` describe, showing ``view`` (see ``launch``)."""
    explorer = settings.create_widget()
    if view:
        # Else (e.g. a storage unreachable now) the explorer as it starts.
        with contextlib.suppress(Exception):
            saved = json.loads(view)
            explorer._restore_view(saved.get("filesystem"), saved.get("folders"))
    return explorer
