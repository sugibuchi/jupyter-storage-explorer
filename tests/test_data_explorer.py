"""DataExplorer: choosing the format to query, and answering the data browser."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from jupyter_storage_explorer import DataExplorer
from jupyter_storage_explorer.query import QuerySettingsStore


class Explorer(DataExplorer):
    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        self.__dict__.setdefault("sent", []).append(content)


def make(url: str, **kwargs: Any) -> Explorer:
    return Explorer(url, query_settings=QuerySettingsStore(), **kwargs)


def test_parquet_file(tmp_path):
    path = tmp_path / "a.parquet"
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(path)
    explorer = make(str(path))
    assert explorer.format == "Parquet"
    assert [c["name"] for c in explorer.query["columns"]] == ["a"]
    explorer._on_custom_msg(
        explorer, {"type": "query_rows", "rid": 3, "offset": 2, "window": 5}, None
    )
    assert explorer.sent[-1] == {
        "type": "reply",
        "rid": 3,
        "offset": 2,
        "columns": ["a"],
        "dtypes": ["Int64"],
        "rows": [[3]],
        "more": False,
        "limited": False,
        "total": 3,  # 3 rows: kept in memory, where they are counted
        "settings": explorer.query["settings"],
    }


def test_delta_table(tmp_path):
    pl.DataFrame({"a": [1]}).write_delta(tmp_path / "t")
    assert make(str(tmp_path / "t")).format == "Delta Lake table"


def test_choose_format(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"x,y\n1,2\n")
    with pytest.raises(ValueError, match="cannot be queried as a table"):
        make(str(path))
    with pytest.raises(ValueError, match=r"cannot be queried as csv"):
        make(str(path), format="csv")


def test_not_queryable(tmp_path):
    path = tmp_path / "a.json"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError, match=r"\(it looks like JSON\)"):
        make(str(path))


def test_format_options(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(b"x\n1\n")
    with pytest.raises(ValueError, match="unknown format_options"):
        make(str(path), format_options={"typo": 1})
    assert (
        make(str(path), format_options={"polars_storage_options": {}}).format == "CSV"
    )
