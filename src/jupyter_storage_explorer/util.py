"""Small helpers for the explorer and its plugins:

- sizes shown to users (``format_size``);
- Python source of keyword arguments, for generated code (``format_kwargs``,
  ``format_arguments``);
- dataclass fields holding secrets, which generated code leaves out
  (``secret_field``, ``secret_dict_field``);
- ``LIBRARY_DEFAULT``, the default of options that are a library's
  arguments, left to the library.
"""

from __future__ import annotations

import dataclasses
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
    "secret_dict_field",
    "secret_field",
]


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


# Field metadata of options: the whole value is a secret (``secret_field``),
# or these keys of a mapping are (``secret_dict_field``).
IS_SECRET = "is_secret"
SECRET_KEYS = "secret_keys"


def secret_field(**kwargs: Any) -> Any:
    """A field of options whose value is a secret, e.g. a password or a
    credential object: ``dataclasses.field(**kwargs)``, marked so, and left
    out of the options' ``repr``.

    Generated code never shows it (``ActionOptions.code_value`` gives None).

    Parameters
    ----------
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(ActionOptions):
    ...     password: str | None = secret_field(default=None)
    """
    metadata = {**kwargs.pop("metadata", {}), IS_SECRET: True}
    kwargs.setdefault("repr", False)
    return dataclasses.field(**kwargs, metadata=metadata)


def secret_dict_field(*, secret_keys: Iterable[str], **kwargs: Any) -> Any:
    """A field of options holding a mapping some of whose keys are secrets,
    e.g. storage options with an account key: ``dataclasses.field(**kwargs)``,
    naming them.

    Generated code shows the mapping without them, at any depth
    (``ActionOptions.code_value``), nor keys that look like credentials
    anyway.

    Parameters
    ----------
    secret_keys : iterable of str
        The keys whose values are secrets, e.g. ``["connection_string",
        "shared_key"]``.
    **kwargs
        ``dataclasses.field``'s, e.g. ``default=None``.

    Examples
    --------
    >>> @dataclass(frozen=True, kw_only=True)
    ... class MyOptions(ActionOptions):
    ...     storage_options: Mapping[str, Any] | None = secret_dict_field(
    ...         default=None, secret_keys=["connection_string", "shared_key"]
    ...     )
    """
    metadata = {**kwargs.pop("metadata", {}), SECRET_KEYS: tuple(secret_keys)}
    return dataclasses.field(**kwargs, metadata=metadata)


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
