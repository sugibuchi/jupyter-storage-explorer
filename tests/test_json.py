"""_json.py: values sent to the frontend."""

from __future__ import annotations

import datetime as dt
import decimal

import polars

from jupyter_storage_explorer._json import jsonable


def test_jsonable():
    assert jsonable(float("nan")) == "nan"
    assert jsonable(dt.date(2025, 1, 2)) == "2025-01-02"
    assert jsonable(decimal.Decimal("1.50")) == "1.50"
    assert jsonable({1: (2, 3)}) == {"1": [2, 3]}
    assert jsonable(polars.Series([1, 2]).to_numpy()) == [1, 2]
    assert jsonable(b"x") == "b'x'"
