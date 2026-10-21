"""Plugins (plugin.py, _plugins.py): which are loaded, what they give the
explorer, and in which order."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import plugin_samples
import pytest
from all_supports import PLUGINS
from explorers import make
from plugin_samples import (
    AvroBySample,
    SampleEngine,
    SampleMapper,
    SampleOperations,
    SampleSupport,
)

from jupyter_storage_explorer import _plugins
from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._plugins import load_plugins
from jupyter_storage_explorer.filesystems import FileSystemMapper, FsspecOperations
from jupyter_storage_explorer.formats import Csv, Engine, FormatSupport
from jupyter_storage_explorer.plugin import ENTRY_POINT_GROUP


def entry_point(name, target):
    return EntryPoint(name, f"plugin_samples:{target}", ENTRY_POINT_GROUP)


@pytest.fixture
def installed(monkeypatch):
    """Fake the plugins installed: their entry points, by name."""

    def install(**targets):
        points = [entry_point(name, target) for name, target in targets.items()]
        monkeypatch.setattr(_plugins, "entry_points", lambda group: points)

    return install


def test_the_repository_plugins():
    # Installed for development: each loads, under its key.
    assert [p.key for p in PLUGINS] == [
        "abfs-support",
        "pandas-support",
        "polars-support",
        "pyspark-support",
    ]


class TestLoading:
    def test_all_by_key(self, installed):
        installed(
            **{"sample-support": "SampleSupport", "other-support": "OtherSupport"}
        )
        plugins, problems = load_plugins(None)
        assert [p.key for p in plugins] == ["other-support", "sample-support"]
        assert problems == []

    def test_those_named_in_their_order(self, installed):
        # Only those named are imported: a broken one not named is no problem.
        installed(
            **{
                "sample-support": "SampleSupport",
                "other-support": "OtherSupport",
                "broken-support": "Missing",
            }
        )
        plugins, problems = load_plugins(["sample-support", "other-support"])
        assert [p.key for p in plugins] == ["sample-support", "other-support"]
        assert problems == []
        assert load_plugins([]) == ([], [])

    def test_unknown_key(self, installed):
        installed(**{"sample-support": "SampleSupport"})
        with pytest.raises(ValueError, match=r"\['polars-suport'\] not installed"):
            load_plugins(["polars-suport"])

    @pytest.mark.parametrize(
        ("target", "problem"),
        [
            ("Missing", "AttributeError"),
            ("NotAPlugin", "is no StorageExplorerPlugin"),
            ("WrongKey", "its class's key is 'another-key'"),
        ],
    )
    def test_left_out_with_the_reason(self, installed, target, problem):
        installed(**{"broken-support": target, "sample-support": "SampleSupport"})
        plugins, problems = load_plugins(None)
        assert plugins == [SampleSupport]  # the others are loaded
        [reason] = problems
        assert reason.startswith("plugin 'broken-support' not loaded")
        assert problem in reason

    def test_one_key_registered_twice(self, monkeypatch):
        points = [entry_point("sample-support", "SampleSupport")] * 2
        monkeypatch.setattr(_plugins, "entry_points", lambda group: points)
        plugins, [problem] = load_plugins(None)
        assert plugins == []
        assert "registered by" in problem


class TestExplorer:
    def test_components_after_those_given_before_the_defaults(self, installed, memfs):
        installed(**{"sample-support": "SampleSupport"})
        given = FsspecOperations()
        mapper = SampleMapper()
        explorer = make("/", fs=memfs, operations=[given], filesystem_mappers=[mapper])
        operations = explorer._operations.operations
        assert operations[0] is given
        assert type(operations[1]) is SampleOperations  # created by the explorer
        mappers = explorer._mappers.mappers
        assert mappers[0] is mapper
        assert type(mappers[1]) is SampleMapper
        assert isinstance(explorer._supports.supports[0], AvroBySample)
        # Its format is detected, and its engine (no view) not offered.
        assert explorer._formats[0].name == "avro"
        assert explorer._engines == []

    def test_no_plugin(self, memfs):
        explorer = make("/", fs=memfs, plugins=[])
        # No engine to choose; the standard formats are detected all the same.
        assert explorer._engines == []
        assert {"parquet", "delta", "csv"} <= set(explorer._format_labels)

    def test_some_plugins(self, memfs):
        explorer = make("/", fs=memfs, plugins=["pandas-support"])
        assert [e["key"] for e in explorer._engines] == ["pandas"]

    def test_a_broken_plugin_warns(self, installed, memfs):
        installed(**{"broken-support": "Missing", "sample-support": "SampleSupport"})
        with pytest.warns(RuntimeWarning, match="plugin 'broken-support' not loaded"):
            explorer = make("/", fs=memfs)
        assert explorer._formats[0].name == "avro"  # the others are used

    def test_unknown_plugin(self, memfs):
        with pytest.raises(ValueError, match="not installed"):
            make("/", fs=memfs, plugins=["polars"])


def test_one_engine_class_per_key():
    # A plugin using another's engine imports its class.
    copy = type("SampleEngine", (Engine,), {"key": "sample", "label": "Copy"})
    other = type(
        "CsvByCopy",
        (FormatSupport,),
        {"format": Csv, "engine": copy, "capabilities": ("recipe",)},
    )
    with pytest.raises(ValueError, match="engine 'sample' is defined twice"):
        SupportChain([AvroBySample, other])
    assert SupportChain([AvroBySample, AvroBySample]).supports  # the same class


def test_samples_are_what_they_claim():
    assert issubclass(SampleMapper, FileSystemMapper)
    assert SampleEngine.key == "sample"
    assert plugin_samples.OtherSupport.format_supports == ()
