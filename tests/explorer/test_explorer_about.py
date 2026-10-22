"""The settings menu's "About" (_explorer/about.py): the explorer, and the
plugins installed."""

from __future__ import annotations

import base64
import pathlib
from importlib.metadata import EntryPoint, version

import pytest
from explorers import make

from jupyter_storage_explorer import _plugins
from jupyter_storage_explorer._static import STATIC
from jupyter_storage_explorer.plugin import ENTRY_POINT_GROUP

ROOT = pathlib.Path(__file__).parents[2]


def about(explorer):
    return explorer.request({"type": "about", "rid": 1})


def test_the_explorer(memfs):
    reply = about(make("/", fs=memfs))
    assert reply["name"] == "Jupyter Storage Explorer"
    assert reply["version"] == version("jupyter-storage-explorer")
    assert reply["authors"] == ["Tsuyoshi SUGIBUCHI"]
    assert reply["license"] == "MIT"
    assert reply["homepage"].startswith("https://github.com/sugibuchi/")
    prefix = "data:image/svg+xml;base64,"
    assert reply["icon"].startswith(prefix)
    assert base64.b64decode(reply["icon"].removeprefix(prefix)).startswith(b"<svg")


def test_the_icon_is_the_launchers():
    # Two copies, one per package: kept the same.
    launcher = ROOT / "launcher" / "labextension" / "style" / "storage-explorer.svg"
    assert (STATIC / "storage-explorer.svg").read_bytes() == launcher.read_bytes()


def test_the_plugins(memfs):
    explorer = make(
        "/", fs=memfs, plugin_options={"pandas-support": {"enabled": False}}
    )
    plugins = {p["key"]: p for p in about(explorer)["plugins"]}
    assert sorted(plugins) == [
        "abfs-support",
        "databricks-support",
        "pandas-support",
        "polars-support",
        "pyspark-support",
    ]
    polars = plugins["polars-support"]
    assert polars == {
        "key": "polars-support",
        "name": "jupyter-storage-explorer-polars-support",
        "version": version("jupyter-storage-explorer-polars-support"),
        "description": "Polars support for Storage Explorer",
        "authors": ["Tsuyoshi SUGIBUCHI"],
        "license": "MIT",
        "homepage": "https://github.com/sugibuchi/jupyter-storage-explorer/tree/main/plugins/polars-support",
        "enabled": True,
        "note": "",
    }
    # Disabled: listed all the same, from its package's metadata.
    pandas = plugins["pandas-support"]
    assert (pandas["enabled"], pandas["note"]) == (False, "Disabled")
    assert pandas["description"] == "pandas support for Storage Explorer"


def test_a_plugin_not_loaded(memfs, monkeypatch):
    point = EntryPoint("broken-support", "plugin_samples:Missing", ENTRY_POINT_GROUP)
    monkeypatch.setattr(_plugins, "entry_points", lambda group: [point])
    with pytest.warns(RuntimeWarning, match="not loaded"):
        explorer = make("/", fs=memfs)
    [plugin] = about(explorer)["plugins"]
    assert plugin["enabled"] is False
    assert plugin["name"] == "broken-support"  # no package: its key
    assert (plugin["authors"], plugin["license"], plugin["homepage"]) == ([], "", "")
    assert plugin["note"].startswith("Not loaded: AttributeError")
