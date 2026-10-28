"""Small helpers for the explorer and its plugins:

- sizes shown to users (``format_size``);
- Python source of keyword arguments, for generated code (``format_kwargs``,
  ``format_arguments``);
- dataclass fields holding secrets, which generated code leaves out
  (``secret_field``, ``secret_dict_field``);
- ``LIBRARY_DEFAULT``, the default of options that are a library's
  arguments, left to the library;
- loggers whose records go where the explorer's do (``get_logger``).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "LIBRARY_DEFAULT",
    "LibraryDefault",
    "format_arguments",
    "format_kwargs",
    "format_size",
    "get_logger",
    "option_field",
    "secret_dict_field",
    "secret_field",
]

# The explorer's logger, which the explorer's logging settings apply to (see
# _logs.py), and the names of the modules of the user's actions files (see
# _extensions/user_actions.py): a digest of the file's path, then its name.
_LOGGER = "jupyter_storage_explorer"
_USER_ACTIONS_MODULE = re.compile(
    r"jupyter_storage_explorer_user_actions_[0-9a-f]+_(?P<stem>.+)"
)


def get_logger(name: str) -> logging.Logger:
    """A logger for an action or a plugin, whose records go where the
    explorer's do: at the level chosen with ``logging_level`` or the Logging
    menu, to the console in a notebook, or to the launcher's log files.

    Also importable from ``jupyter_storage_explorer`` and
    ``jupyter_storage_explorer.actions``.

    Parameters
    ----------
    name : str
        The module's ``__name__``.

    Returns
    -------
    logging.Logger
        A child of the explorer's logger, ``jupyter_storage_explorer``:

        - ``jupyter_storage_explorer.user_actions.<file>`` in a user's actions
          file, e.g. ``jupyter_storage_explorer.user_actions.actions`` for
          ``actions.py``;
        - the explorer's own modules' loggers as they are;
        - else ``jupyter_storage_explorer.ext.<name>``, e.g. for a plugin's
          modules, or ``__main__`` in a notebook.

    Examples
    --------
    >>> from jupyter_storage_explorer.actions import get_logger
    >>> log = get_logger(__name__)
    >>> log.info("Reading %s", path)  # doctest: +SKIP
    """
    if name == _LOGGER or name.startswith(_LOGGER + "."):
        return logging.getLogger(name)
    if match := _USER_ACTIONS_MODULE.fullmatch(name):
        return logging.getLogger(f"{_LOGGER}.user_actions.{match['stem']}")
    return logging.getLogger(f"{_LOGGER}.ext.{name}")


def format_size(size: float) -> str:
    """A size in bytes as users read it, e.g. "512 B", "1.5 KB", "586 MB".

    Under 10 of a unit it keeps one decimal, unless it is 0, e.g. "2 KB";
    from 10 it is rounded, e.g. "10 MB".

    Parameters
    ----------
    size : int or float
        The size in bytes.

    Returns
    -------
    str
        The size in B, KB, MB, GB or TB, with 1 KB being 1024 bytes.

    Examples
    --------
    >>> format_size(1536)
    '1.5 KB'
    >>> format_size(10 * 1024 * 1024)
    '10 MB'
    """
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B" or size >= 10:
        return f"{size:,.0f} {unit}"
    return f"{size:.1f}".removesuffix(".0") + f" {unit}"


def format_kwargs(**kwargs: Any) -> str:
    """Python source for keyword arguments following others in a call, each
    after ", "; those that are None are left out, so it may be empty. For the
    ``{kwargs}`` of code templates, e.g. ``"df = pl.read_csv({url}{kwargs})"``,
    with options as ``ActionOptions.code_value`` gives them.

    >>> format_kwargs(sep=";", storage_options=None)
    ", sep=';'"
    """
    return "".join(f", {k}={v!r}" for k, v in kwargs.items() if v is not None)


def format_arguments(arguments: Mapping[str, Any]) -> str:
    """Python source for keyword arguments following others in a call, each
    after ", ", None included: for ``ActionOptions.code_arguments``.

    >>> format_arguments({"has_header": False, "quote_char": None})
    ", has_header=False, quote_char=None"
    """
    return "".join(f", {k}={v!r}" for k, v in arguments.items())


# Option names that look like credentials are left out of generated code,
# since code gets copied, shared and saved in notebooks: a safety net under
# the secrets options declare (secret_field, secret_dict_field).
_SECRET_OPTION = re.compile(
    r"key|secret|token|password|passwd|credential|sas|connection_string", re.IGNORECASE
)


def _is_plain(value: Any) -> bool:
    """Whether ``repr(value)`` is valid Python, so it can appear in generated code."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_plain(v) for v in value)
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _is_plain(v) for k, v in value.items())
    return False


def _shown_options(
    options: Mapping[str, Any] | None, secret_keys: frozenset[str]
) -> dict[str, Any]:
    """``options`` fit to put in generated code; empty for None: without
    ``secret_keys`` (at any depth), names that look like credentials anyway,
    and values that are objects rather than plain data (e.g. the filesystem
    a DirFileSystem wraps)."""
    out: dict[str, Any] = {}
    for key, value in (options or {}).items():
        if key in secret_keys or _SECRET_OPTION.search(key):
            continue
        if isinstance(value, Mapping):
            # Filtered key by key, keeping e.g. client_kwargs' endpoint_url.
            out[key] = _shown_options(value, secret_keys)
        elif _is_plain(value):
            out[key] = value
    return out


# Field metadata of options: what the option is for (``option_field``), how
# its default is shown, the whole value is a secret (``secret_field``), or
# these keys of a mapping are (``secret_dict_field``).
DESCRIPTION = "description"
SHOWN_DEFAULT = "shown_default"
IS_SECRET = "is_secret"
SECRET_KEYS = "secret_keys"


def option_field(
    description: str, *, shown_default: str | None = None, **kwargs: Any
) -> Any:
    """A field of options, with its description: ``dataclasses.field(**kwargs)``.

    Every field of actions' and plugins' options has one. The plugins'
    READMEs show it in their tables of options, and settings forms may too.

    Parameters
    ----------
    description : str
        What the option does, in Markdown: one or a few sentences, lines
        separated by ``"\\n"``.
    shown_default : str, optional
        The default as the docs show it, in Markdown, where its value does
        not say it, e.g. "``True``" for ``LIBRARY_DEFAULT`` left to a library
        defaulting to True, or "detected". By default the value itself.
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(ActionOptions):
    ...     header: bool | LibraryDefault = option_field(
    ...         "Whether the first row names the columns.",
    ...         default=LIBRARY_DEFAULT,
    ...         shown_default="`True`",
    ...     )
    """
    metadata = _described(kwargs.pop("metadata", {}), description, shown_default)
    return dataclasses.field(**kwargs, metadata=metadata)


def _described(
    metadata: Mapping[str, Any], description: str | None, shown_default: str | None
) -> dict[str, Any]:
    """``metadata`` with the description and shown default given."""
    described = dict(metadata)
    if description is not None:
        described[DESCRIPTION] = description
    if shown_default is not None:
        described[SHOWN_DEFAULT] = shown_default
    return described


def secret_field(
    *, description: str | None = None, shown_default: str | None = None, **kwargs: Any
) -> Any:
    """A field of options whose value is a secret, e.g. a password or a
    credential object: ``option_field``'s, marked so, and left out of the
    options' ``repr``.

    Generated code never shows it (``ActionOptions.code_value`` gives None).

    Parameters
    ----------
    description, shown_default : str, optional
        As for ``option_field``: a plugin's options need a description.
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(ActionOptions):
    ...     password: str | None = secret_field(
    ...         description="The database's password.", default=None
    ...     )
    """
    metadata = {**kwargs.pop("metadata", {}), IS_SECRET: True}
    kwargs.setdefault("repr", False)
    return dataclasses.field(
        **kwargs, metadata=_described(metadata, description, shown_default)
    )


def secret_dict_field(
    *,
    secret_keys: Iterable[str],
    description: str | None = None,
    shown_default: str | None = None,
    **kwargs: Any,
) -> Any:
    """A field of options holding a mapping some of whose keys are secrets,
    e.g. storage options with an account key: ``option_field``'s, naming
    them.

    Generated code shows the mapping without them, at any depth
    (``ActionOptions.code_value``), nor keys that look like credentials
    anyway.

    Parameters
    ----------
    secret_keys : iterable of str
        The keys whose values are secrets, e.g. ``["connection_string",
        "shared_key"]``.
    description, shown_default : str, optional
        As for ``option_field``: a plugin's options need a description.
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(ActionOptions):
    ...     storage_options: Mapping[str, Any] | None = secret_dict_field(
    ...         description="The storage's options.",
    ...         default=None,
    ...         secret_keys=["connection_string", "shared_key"],
    ...     )
    """
    metadata = {**kwargs.pop("metadata", {}), SECRET_KEYS: tuple(secret_keys)}
    return dataclasses.field(
        **kwargs, metadata=_described(metadata, description, shown_default)
    )


class LibraryDefault:
    """The type of ``LIBRARY_DEFAULT``, the default of options that are a
    library's arguments: one object, never equal to a value given."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "LIBRARY_DEFAULT"

    def __reduce__(self) -> str:
        # Pickled (e.g. copied) as the module's object itself.
        return "LIBRARY_DEFAULT"


LIBRARY_DEFAULT = LibraryDefault()
"""The default of an option that is one of the library's arguments: not
passed, so the library's own default applies (``ActionOptions.arguments``).
Not None, which some arguments take as a value (e.g. polars'
``quote_char=None``: no quoting)."""
