"""Reading fsspec info dicts, whose keys differ between filesystems."""

from __future__ import annotations

import datetime as dt
from typing import Any

# Keys used by different fsspec implementations for the modification time
# (local: mtime, s3fs: LastModified, adlfs: last_modified, gcsfs: updated).
_MTIME_KEYS = (
    "mtime",
    "LastModified",
    "last_modified",
    "updated",
    "modified",
    "created",
)


def _to_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def mtime(info: dict[str, Any]) -> float | None:
    """The modification time in an fsspec info dict (seconds), whichever key
    its filesystem uses, or None."""
    return next(
        (ts for key in _MTIME_KEYS if (ts := _to_timestamp(info.get(key))) is not None),
        None,
    )
