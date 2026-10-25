"""Small helpers for the explorer and its plugins, e.g. sizes shown to users
(``format_size``)."""

from __future__ import annotations

__all__ = ["format_size"]


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
