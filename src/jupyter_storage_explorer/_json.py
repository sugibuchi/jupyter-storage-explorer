"""Values sent to the frontend as JSON: table cells, previews, fsspec info."""

from __future__ import annotations

import datetime as dt
import decimal
import math
from typing import Any


def jsonable(value: Any) -> Any:
    """A value the frontend can receive: dates, decimals, numpy scalars etc. become JSON types."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    # pandas' missing values (pd.NA, pd.NaT), without importing pandas.
    if type(value).__name__ in ("NAType", "NaTType"):
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if callable(getattr(value, "tolist", None)):  # numpy scalar or array
        return jsonable(value.tolist())
    return str(value)
