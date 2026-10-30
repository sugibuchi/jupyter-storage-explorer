"""Explorers configured in layers, by files in Jupyter's configuration
directories (``jupyter --paths``, config section): e.g. ``~/.jupyter`` for
the user, ``<env>/etc/jupyter`` for the environment, ``/usr/local/etc/jupyter``
and ``/etc/jupyter`` for the system.

- ``storage-explorer/common.py`` configures every ``StorageExplorer``, in
  notebooks and in the launcher's tabs alike, unless it is created with
  ``common_config="disabled"``.
- ``storage-explorer/launcher.py`` configures the launcher's tabs and side
  panel only (see the launcher's ``launcher.py``).

Every file found is a layer: they are applied from the last directory (the
system's) to the first (usually the user's; in a virtual environment,
Jupyter searches the environment's first), each adding to or overriding the
settings of those before, except the settings they made final. In each
directory, ``common.py`` comes before ``launcher.py``, which overrides it.
An explorer's own arguments come last, over the files' settings.

Each file may have these functions, all optional:

``filesystems()``
    ``{name: URL or fsspec filesystem}``, merged by name: a later layer adds
    entries or replaces them, and removes them with ``None``. An explorer
    created with a path, ``fs``, ``filesystems`` or storage options shows
    those instead. Without any, it browses its kernel's folder (``"."``).
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
    defaults'. Two actions of one kind, format, engine and label are an
    error: give yours another label.
``engine_options()``
    ``{engine key: {format or "*": {option: value}}}`` for the actions (see
    ``StorageExplorer``'s ``engine_options``), merged option by option (a
    value is replaced whole, e.g. a ``storage_options`` dict). Options may
    be a function of the item's location returning them: merged with
    another layer's, the later layer's options still win option by option.
    A ``by_protocol`` merged with dicts stays one, which the explorer checks.
``filesystem_operations()``
    ``[FileSystemOperations, ...]``: file operations of your own (see
    ``StorageExplorer``'s ``filesystem_operations``), tried before the plugins' and
    ``StorageExplorer.default_operations()``; a later layer's come first.
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
``final()``
    ``["filesystems", "height", ...]``: settings later layers cannot change,
    an explorer's arguments neither: the names of the functions above,
    except ``parameters``, and the names of parameters. A later layer's
    attempt is ignored, with a warning. This is a convenience for
    administrators, not a security boundary: users can always create
    explorers with ``common_config="disabled"``.

The user's files (``user_files`` of ``load_settings``) with an error are left
out, with a warning, so that the explorer still opens. An error in another
file, an administrator's, stops it.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.util
import inspect
import pathlib
import warnings
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from jupyter_core.paths import jupyter_config_dir, jupyter_config_path

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Looked for in each Jupyter configuration directory.
COMMON_FILE = pathlib.Path("storage-explorer", "common.py")
LAUNCHER_FILE = pathlib.Path("storage-explorer", "launcher.py")

# The functions a file may have, besides parameters() and final(), with how
# each one's values are merged with those of earlier layers (see the module
# docstring); parameters() is merged parameter by parameter.
MERGES = {
    "filesystems": "by name",
    "plugin_options": "by plugin",
    "actions": "first",
    "engine_options": "by option",
    "filesystem_operations": "first",
    "filesystem_mappers": "first",
    "transfer_policy": "first",
}

# The functions a file may have, besides final().
HOOKS = (*MERGES, "parameters")

# Former names of functions, taken for the new ones, also in final(). To be
# removed in the major release.
ALIASES = {"format_options": "engine_options"}

# Functions files may still have, no longer used: they are ignored (and
# their names in final()), with a warning.
RETIRED = {
    # The whole configuration, before the functions above.
    "launch": "set filesystems(), parameters() etc. instead (see Configuration files in docs/storage-explorer.md)",
    # CSS applied to the page while the tab was open: not to explorers in
    # notebooks, which JupyterLab's custom.css reaches.
    "style": "use JupyterLab's custom.css instead, for every page (see Icons in the project's DEVELOPMENT.md)",
    # Formats are those of the actions.
    "formats": "give actions() of your formats instead: explorers detect their formats",
    # FormatSupport classes, replaced by actions.
    "supports": "give actions() instead: functions decorated with @view or @code (see the plugin guide)",
}

# StorageExplorer's arguments giving the storages it shows, which
# filesystems() gives in files.
STORAGE_ARGUMENTS = ("path", "fs", "filesystems")

# StorageExplorer's arguments merged with the functions' settings, not
# replacing parameters'.
_MERGED_ARGUMENTS = frozenset({*STORAGE_ARGUMENTS, *MERGES, *ALIASES})

# StorageExplorer arguments that are not "parameters": set by their own
# function (or one of its former names, see ALIASES), by filesystems(), or
# never by files.
_NOT_PARAMETERS = frozenset(
    {"self", *STORAGE_ARGUMENTS, "common_config", *MERGES, *ALIASES}
)


class ConfigError(ValueError):
    """A configuration file that cannot be used: the message names it."""


@dataclasses.dataclass
class Settings:
    """The settings of all the layers, merged (see the module docstring).

    ``warnings`` are the changes ignored because an earlier layer made the
    setting final, and the functions no longer used (see ``RETIRED``).
    ``files`` are the layers applied, in the order applied, and ``final``
    the settings made final, with the file that did. ``user_errors`` say why
    the user's files were left out, if they were (see ``load_settings``).
    """

    filesystems: dict[str, Any] = dataclasses.field(default_factory=dict)
    # {plugin key: {option: value}}
    plugin_options: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    actions: list[Any] = dataclasses.field(default_factory=list)
    # {engine key: {format or "*": a dict of options, or a function of the location}}
    engine_options: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    filesystem_operations: list[Any] = dataclasses.field(default_factory=list)
    filesystem_mappers: list[Any] = dataclasses.field(default_factory=list)
    transfer_policy: list[Any] = dataclasses.field(default_factory=list)
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    warnings: list[str] = dataclasses.field(default_factory=list)
    files: list[pathlib.Path] = dataclasses.field(default_factory=list)
    final: dict[str, pathlib.Path] = dataclasses.field(default_factory=dict)
    user_errors: list[str] = dataclasses.field(default_factory=list)

    @property
    def shown_filesystems(self) -> dict[str, Any]:
        """The storages offered: ``filesystems`` without those removed."""
        return {k: v for k, v in self.filesystems.items() if v is not None}

    def under(
        self, given: Mapping[str, Any], storage_options: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """``StorageExplorer``'s keyword arguments: those ``given`` (with
        ``storage_options``) over these settings, merged as a layer's
        functions are; and the warnings of those ignored, as final."""
        ignored: list[str] = []

        def allowed(name: str) -> bool:
            if name not in self.final:
                return True
            ignored.append(
                f"StorageExplorer's {name} argument is ignored: it is final in "
                f"{self.final[name]}"
            )
            return False

        arguments: dict[str, Any] = dict(self.parameters)
        storage = {n: given[n] for n in STORAGE_ARGUMENTS if given.get(n) is not None}
        if (storage or storage_options) and allowed("filesystems"):
            arguments.update(storage, **storage_options)
        elif self.shown_filesystems:
            arguments["filesystems"] = self.shown_filesystems
        arguments.update(self._merged_with(given, allowed))
        arguments.update(
            (name, value)
            for name, value in given.items()
            if name not in _MERGED_ARGUMENTS and allowed(name)
        )
        return arguments, ignored

    def _merged_with(
        self, given: Mapping[str, Any], allowed: Callable[[str], bool]
    ) -> dict[str, Any]:
        """The functions' settings, but filesystems(), with the arguments
        ``given`` of their names merged over them, if ``allowed``."""
        merged = {}
        for name, merge in MERGES.items():
            if name == "filesystems":
                continue
            # The former name, if given, keeps its deprecation warning.
            key = next(
                (a for a, n in ALIASES.items() if n == name and a in given), name
            )
            theirs = given.get(key)
            if theirs is not None and not allowed(name):
                theirs = None
            if value := _over(merge, getattr(self, name), theirs):
                merged[key] = value
        return merged


def _over(merge: str, ours: Any, theirs: Any) -> Any:
    """An explorer's argument ``theirs`` merged over the files' ``ours``, as a
    later layer's function is. Values that are not of the argument's type are
    given as they are, for the explorer to report."""
    if theirs is None:
        return list(ours) if isinstance(ours, list) else ours
    if merge == "by plugin":
        if not isinstance(theirs, Mapping):
            return theirs
        merged = {key: dict(options) for key, options in ours.items()}
        for key, options in theirs.items():
            if isinstance(options, Mapping):
                merged.setdefault(key, {}).update(options)
            else:
                merged[key] = options
        return merged
    if merge == "by option":
        from jupyter_storage_explorer.engine import (  # noqa: PLC0415
            _merged_engine_options,
        )

        if not isinstance(theirs, Mapping):
            return theirs
        return _merged_engine_options([ours, theirs])
    # "first"
    if isinstance(theirs, (str, bytes, Mapping)) or not isinstance(theirs, Iterable):
        return theirs
    return [*theirs, *ours]


def find_config_files(names: Sequence[pathlib.Path]) -> list[pathlib.Path]:
    """The files ``names`` (e.g. ``LAUNCHER_FILE``, then ``COMMON_FILE``) in
    Jupyter's order: the user's first, the system's last; in each directory,
    in the order of ``names``. They are applied the other way round."""
    files = []
    for directory in jupyter_config_path():
        for name in names:
            path = pathlib.Path(directory) / name
            if path.is_file() and path not in files:
                files.append(path)
    return files


def user_common_file() -> pathlib.Path:
    """The user's common.py, in their Jupyter configuration directory
    (``~/.jupyter`` unless ``JUPYTER_CONFIG_DIR`` is set); it may not exist."""
    return pathlib.Path(jupyter_config_dir(), COMMON_FILE)


def load_settings(
    files: Sequence[pathlib.Path],
    *,
    user_files: Sequence[pathlib.Path],
    into: Settings | None = None,
) -> Settings:
    """Merge the settings of ``files``, in Jupyter's order (see
    ``find_config_files``), applied from the last (the system's) to the
    first (the user's), into ``into`` (default: new ``Settings``).

    Raises ConfigError if a file cannot be loaded, a function fails, or
    returns names that do not exist. Except the user's files, ``user_files``:
    they are left out instead, with their errors in ``Settings.user_errors``,
    so that the explorer still opens and the user can fix them.
    """
    settings = Settings() if into is None else into
    for path in reversed(files):
        try:
            values, warnings = _read_layer(path)
            _check_layer(values, path, settings.final)
        except ConfigError as exc:
            if not any(same_file(path, user) for user in user_files):
                raise
            settings.user_errors.append(str(exc))
            continue
        settings.warnings += warnings
        _apply(settings, values, path, settings.final)
        for name in values["final"] or ():
            if name not in RETIRED:  # its function is ignored anyway
                settings.final.setdefault(name, path)
        settings.files.append(path)
    return settings


def _read_layer(path: pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    """What the functions of file ``path`` return, by name, and the warnings
    of the functions no longer used. ConfigError if it cannot be loaded, or
    a function fails."""
    module = _load(path)
    warnings = []
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
                raise ConfigError(
                    f"{path}: give {new}() only: {old}() is its former name"
                )
            values[new] = value
    if values["final"]:
        values["final"] = [ALIASES.get(name, name) for name in values["final"]]
    return values, warnings


def _check_layer(
    values: dict[str, Any], path: pathlib.Path, final: dict[str, pathlib.Path]
) -> None:
    """ConfigError if a layer's ``values`` cannot be applied: checked before
    applying them, so that a layer with an error leaves the settings as they
    were. Its checks are those of ``_apply`` (applied to settings of their own
    here), and the names given to ``final()``."""
    _apply(Settings(), values, path, dict(final))
    for name in values["final"] or ():
        if name not in RETIRED:
            _check_final_name(name, path)


def same_file(path: pathlib.Path, other: pathlib.Path) -> bool:
    """Whether ``path`` and ``other`` name the same file."""
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
    for name, merge in MERGES.items():
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


def _load(path: pathlib.Path) -> Any:
    """Import ``path`` as a module of its own."""
    spec = importlib.util.spec_from_file_location(
        f"storage_explorer_config_{abs(hash(str(path)))}", path
    )
    if spec is None or spec.loader is None:
        raise ConfigError(f"{path}: cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ConfigError(f"{path}: {type(exc).__name__}: {exc}") from exc
    return module


def _call(module: Any, path: pathlib.Path, name: str) -> Any:
    """What ``module``'s function ``name`` returns; None if it has none."""
    function = getattr(module, name, None)
    if function is None:
        return None
    if not callable(function):
        raise ConfigError(f"{path}: {name} must be a function")
    try:
        return function()
    except Exception as exc:
        raise ConfigError(f"{path}: {name}(): {type(exc).__name__}: {exc}") from exc


def _merge_plugin_options(
    merged: dict[str, dict[str, Any]], value: Any, path: pathlib.Path
) -> None:
    """Merge one layer's ``plugin_options()`` into ``merged``: by plugin, then
    option, so a layer disables a plugin, or changes one option of it,
    without restating the others. Whether they exist is checked by the
    explorer."""
    for key, options in _mapping(value, path, "plugin_options").items():
        if not isinstance(options, dict):
            raise ConfigError(
                f"{path}: plugin_options(): {key!r} must map option names to values"
            )
        merged.setdefault(key, {}).update(options)


def _mapping(value: Any, path: pathlib.Path, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: {name}() must return a dict")
    return value


def _merge_engine_options(
    merged: dict[str, dict[str, Any]], value: Any, path: pathlib.Path
) -> None:
    """Merge one layer's ``engine_options()`` into ``merged``: by engine,
    format, then option, so a layer changes one option of a format without
    restating the others. Whether the names exist is checked by the explorer."""
    from jupyter_storage_explorer.engine import _merged_options  # noqa: PLC0415

    for library, by_format in _mapping(value, path, "engine_options").items():
        if not isinstance(by_format, dict) or not all(
            isinstance(options, dict) or callable(options)
            for options in by_format.values()
        ):
            raise ConfigError(
                f"{path}: engine_options(): {library!r} must map format names "
                f'(or "*") to dicts of options, or functions of the location '
                f"returning them"
            )
        formats = merged.setdefault(library, {})
        for name, options in by_format.items():
            formats[name] = _merged_options(formats.get(name), options)


def _sequence(value: Any, path: pathlib.Path, name: str) -> list[Any]:
    if isinstance(value, (str, bytes, dict)) or not hasattr(value, "__iter__"):
        raise ConfigError(f"{path}: {name}() must return a list")
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
    if name in MERGES or name in ALIASES:
        raise ConfigError(
            f"{path}: parameters(): {name} is set by its own function, not parameters()"
        )
    if name in STORAGE_ARGUMENTS:
        raise ConfigError(f"{path}: parameters(): {name} is set by filesystems()")
    if name == "common_config":
        raise ConfigError(
            f"{path}: parameters(): {name} is an argument of explorers only"
        )
    if name not in _parameter_names():
        raise ConfigError(f"{path}: parameters(): unknown parameter {name!r}")


def _check_final_name(name: str, path: pathlib.Path) -> None:
    if name in MERGES:
        return
    if name not in _parameter_names():
        raise ConfigError(
            f"{path}: final(): unknown setting {name!r} (a function name other "
            f"than parameters, or a parameter name)"
        )


def with_common_config(init: Callable[..., None]) -> Callable[..., None]:
    """``StorageExplorer.__init__``, taking the settings of the common.py
    files under the arguments given, unless ``common_config="disabled"``.

    The warnings of the files, and of the arguments ignored as final, point
    at the code creating the explorer. An error the explorer raises with
    these settings notes the files."""
    signature = inspect.signature(init)

    @functools.wraps(init)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("common_config", "enabled") != "enabled":
            init(self, *args, **kwargs)  # which checks the value
            return
        settings = load_settings(
            find_config_files([COMMON_FILE]), user_files=[user_common_file()]
        )
        problems = [*settings.warnings]
        problems += [f"Your common.py was left out: {e}" for e in settings.user_errors]
        for problem in problems:
            warnings.warn(problem, RuntimeWarning, stacklevel=2)
        if not settings.files:
            init(self, *args, **kwargs)
            return
        bound = signature.bind(self, *args, **kwargs).arguments
        given = {k: v for k, v in bound.items() if k not in ("self", "storage_options")}
        arguments, ignored = settings.under(given, bound.get("storage_options", {}))
        for warning in ignored:
            warnings.warn(warning, RuntimeWarning, stacklevel=2)
        try:
            init(self, **arguments)
        except Exception as exc:
            exc.add_note(
                "With the settings of "
                + ", ".join(str(path) for path in settings.files)
            )
            raise

    return wrapper
