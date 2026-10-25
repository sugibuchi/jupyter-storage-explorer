"""Formats users define in a line, for their actions (``file_format``): files
or folders recognised by their names, e.g. ``file_format(extensions=".abc")``.

They rank below every other format (``UserDefinedFormat.priority``): an item
the explorer or a plugin already recognises keeps its format, and a user
format matching it too is offered as another one, in "Preview as". The same
arguments give the same format, so that actions in several files can share
it, and so that files read again (by each explorer created, or by "Reload
actions") define it once
for the kernel's life."""

from __future__ import annotations

import fnmatch
import itertools
from typing import TYPE_CHECKING, Any, ClassVar

from jupyter_storage_explorer.formats.base import DataFormat

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jupyter_storage_explorer.formats.base import ItemContext

__all__ = ["UserDefinedFormat", "file_format"]

# The formats file_format made, by its arguments, and the numbers of their
# names, in the order they were made.
_MADE: dict[tuple[Any, ...], type[UserDefinedFormat]] = {}
_NUMBERS = itertools.count(1)


class UserDefinedFormat(DataFormat):
    """A format made by ``file_format``: files, or folders, whose names end
    with one of ``extensions`` or match one of ``names``, glob patterns, both
    ignoring case.

    Attributes
    ----------
    names : tuple of str
        Glob patterns of whole names, lower case, e.g. ``("dockerfile",)``.
    for_folders : bool
        Whether it is a format of folders rather than files.
    """

    # Below the explorer's fallback, Text (-10): a format of the explorer or a
    # plugin matching an item is its format; this one, another.
    priority = -20
    names: ClassVar[tuple[str, ...]] = ()
    for_folders: ClassVar[bool] = False

    def matches(self, ctx: ItemContext) -> bool:
        """Whether the item is a file (a folder, with ``for_folders``) whose
        name ends with one of ``extensions`` or matches one of ``names``."""
        if ctx.is_dir != self.for_folders:
            return False
        name = ctx.name.lower()
        return name.endswith(self.extensions) or any(
            fnmatch.fnmatchcase(name, pattern) for pattern in self.names
        )


def file_format(
    extensions: str | Iterable[str] | None = None,
    *,
    names: str | Iterable[str] | None = None,
    is_dir: bool = False,
    label: str | None = None,
    name: str | None = None,
    file_icon: str | tuple[str, str] | None = None,
) -> type[UserDefinedFormat]:
    """A format of files (or folders) recognised by their names, for actions
    of your own: ``@code(file_format(".abc"))``.

    Use the explorer's or a plugin's format when one exists, e.g. ``Json``
    for JSON files: this one ranks below them all (see the module
    docstring).

    Parameters
    ----------
    extensions : str or iterable of str, optional
        Name endings, e.g. ``".abc"`` or ``[".yml", ".yaml"]``; a leading "."
        is added if missing. Case is ignored.
    names : str or iterable of str, optional
        Glob patterns of whole names, e.g. ``"Dockerfile"`` or
        ``"*.zarr"``. Case is ignored.
    is_dir : bool, default False
        A format of folders, e.g. ``file_format(names="*.zarr",
        is_dir=True)``, rather than files.
    label : str, optional
        Shown to the user; by default its patterns, e.g. "Files (.abc)".
    name : str, optional
        Its identifier, e.g. in ``engine_options``; by default
        "user-format-1", "user-format-2"..., in the order they are made.
    file_icon : str or tuple of (str, str), optional
        The icon of its files, as ``DataFormat.file_icon``.

    Returns
    -------
    type of UserDefinedFormat
        The format class, the same for the same arguments.

    Raises
    ------
    TypeError
        Without ``extensions`` or ``names``.
    """
    endings = tuple(
        e if e.startswith(".") else f".{e}" for e in _strings(extensions, "extensions")
    )
    patterns = _strings(names, "names")
    if not endings and not patterns:
        raise TypeError("file_format needs extensions or names")
    key = (endings, patterns, bool(is_dir), label, name, file_icon)
    made = _MADE.get(key)
    if made is not None:
        return made
    number = next(_NUMBERS)
    shown = ", ".join([*endings, *patterns])
    attributes = {
        "name": name or f"user-format-{number}",
        "label": label or f"{'Folders' if is_dir else 'Files'} ({shown})",
        "extensions": endings,
        "names": patterns,
        "for_folders": bool(is_dir),
        "file_icon": file_icon,
        "__module__": __name__,
    }
    made = type(f"UserDefinedFormat{number}", (UserDefinedFormat,), attributes)
    _MADE[key] = made
    return made


def _strings(value: str | Iterable[str] | None, what: str) -> tuple[str, ...]:
    """``value`` as a tuple of lower-case strings: one, several, or none."""
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else tuple(value)
    if not all(isinstance(v, str) and v for v in values):
        raise TypeError(f"file_format: {what} must be strings, not {value!r}")
    return tuple(v.lower() for v in values)
