"""Shared fixtures: filesystems with data in them, and items to detect formats on."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import Explorer, make

# memfs and make_item, as plugins test with.
pytest_plugins = ["jupyter_storage_explorer.testing"]


@pytest.fixture(autouse=True)
def jupyter_data_dir(tmp_path_factory, monkeypatch):
    """A Jupyter data folder of each test's own: notebooks saved through
    "Open in JupyterLab" record their signatures in nbformat's notary
    database there, never in the user's."""
    folder = tmp_path_factory.mktemp("jupyter-data")
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(folder))
    return folder


@pytest.fixture
def mem_explorer(memfs) -> Explorer:
    memfs.pipe_file("/data/a.csv", b"x,y\n1,2\n")
    memfs.pipe_file("/data/notes.md", b"# Notes\n")
    memfs.pipe_file("/data/table/_delta_log/0.json", b"{}")
    memfs.pipe_file("/other/b.txt", b"b")
    return make("/", fs=memfs)


@pytest.fixture
def local(tmp_path) -> Explorer:
    """An explorer of a local folder, as polars reads local paths."""
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(tmp_path / "data.parquet")
    (tmp_path / "notes.txt").write_bytes(b"hello\n")
    return make(str(tmp_path))
