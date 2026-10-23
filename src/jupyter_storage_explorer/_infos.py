"""Reading fsspec info dicts, whose keys differ between filesystems."""

from __future__ import annotations

import datetime as dt
from typing import Any

# Keys used by different fsspec implementations for the modification time
# (local: mtime, s3fs: LastModified, adlfs: last_modified, gcsfs: updated,
# huggingface_hub: last_commit, with expand_info=True).
_MTIME_KEYS = (
    "mtime",
    "LastModified",
    "last_modified",
    "updated",
    "modified",
    "last_commit",
    "created",
)

# And for the creation time (local and memory: created, adlfs: creation_time,
# gcsfs: timeCreated).
_CTIME_KEYS = ("created", "creation_time", "timeCreated")


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
    # A commit's details, with its date: huggingface_hub's LastCommitInfo,
    # or a dict of them.
    date = (
        value.get("date") if isinstance(value, dict) else getattr(value, "date", None)
    )
    if isinstance(date, (dt.datetime, str)):
        return _to_timestamp(date)
    return None


def _first_time(info: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    return next(
        (ts for key in keys if (ts := _to_timestamp(info.get(key))) is not None),
        None,
    )


def mtime(info: dict[str, Any]) -> float | None:
    """The modification time in an fsspec info dict (seconds), whichever key
    its filesystem uses, or None."""
    return _first_time(info, _MTIME_KEYS)


def ctime(info: dict[str, Any]) -> float | None:
    """The creation time in an fsspec info dict (seconds), or None where the
    filesystem's listing does not give it (s3fs). Local files' is fsspec's
    "created", ``st_ctime``: on Linux the last change of the file's metadata,
    as in JupyterLab's file browser."""
    return _first_time(info, _CTIME_KEYS)
