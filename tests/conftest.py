"""Shared fixtures: filesystems with data in them, and items to detect formats on."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import Explorer, make

from jupyter_storage_explorer import _logs

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


@pytest.fixture(autouse=True)
def jupyter_config_dirs(tmp_path_factory, monkeypatch):
    """Jupyter configuration folders of each test's own, none read by
    default: explorers never load the actions or the common.py of the
    user's files, nor create the user's actions.py in ~/.jupyter (the
    user's folder is an empty one of the test's). A test adds folders to the
    list it returns, the user's first."""
    folders: list[str] = []
    user = tmp_path_factory.mktemp("jupyter-config")
    for module in ("user_actions", "config"):
        monkeypatch.setattr(
            f"jupyter_storage_explorer._extensions.{module}.jupyter_config_path",
            lambda: folders,
        )
        monkeypatch.setattr(
            f"jupyter_storage_explorer._extensions.{module}.jupyter_config_dir",
            lambda: str(user),
        )
    # Log files too, in the same folder (see _logs.py).
    monkeypatch.setattr(
        "jupyter_storage_explorer._logs.jupyter_config_dir", lambda: str(user)
    )
    return folders


@pytest.fixture(autouse=True)
def logs_reset():
    """The package's logger as Python makes it after each test: explorers
    configure it for the kernel (see _logs.py)."""
    yield
    _logs.reset()


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
