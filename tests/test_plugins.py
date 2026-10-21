"""Plugins (plugin.py, _plugins.py): which are loaded, with which options,
what they give the explorer, and in which order."""

from __future__ import annotations

from importlib.metadata import EntryPoint, version

import pytest
from all_supports import NO_PLUGINS, PLUGINS
from explorers import make
from jupyter_storage_explorer_polars_support import PolarsSupport
from plugin_samples import (
    AvroBySample,
    SampleMapper,
    SampleOperations,
    SampleSupport,
    SampleSupportOptions,
)

from jupyter_storage_explorer import _plugins
from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._plugins import load_plugins
from jupyter_storage_explorer.filesystems import FsspecOperations
from jupyter_storage_explorer.formats import Csv, Engine, FormatSupport
from jupyter_storage_explorer.plugin import (
    ENTRY_POINT_GROUP,
    LOWEST_PRIORITY,
    StorageExplorerPluginOptions,
)


def entry_point(name, target):
    return EntryPoint(name, f"plugin_samples:{target}", ENTRY_POINT_GROUP)


@pytest.fixture
def installed(monkeypatch):
    """Fake the plugins installed: their entry points, by name."""

    def install(**targets):
        points = [entry_point(name, target) for name, target in targets.items()]
        monkeypatch.setattr(_plugins, "entry_points", lambda group: points)

    return install


def keys(plugins):
    return [p.key for p in plugins]


def test_the_repository_plugins():
    # Installed for development: each loads, under its key.
    assert keys(PLUGINS) == [
        "abfs-support",
        "pandas-support",
        "polars-support",
        "pyspark-support",
    ]


class TestMetadata:
    """A plugin's name, description and version: its package's metadata,
    from its pyproject.toml's [project]."""

    def test_of_the_repository_plugins(self):
        explorer_version = version("jupyter-storage-explorer")
        for plugin in PLUGINS:
            assert plugin.name == f"jupyter-storage-explorer-{plugin.key}"
            assert plugin.version == explorer_version  # released together
            assert plugin.description.endswith(" support for Storage Explorer")

    def test_of_a_plugin_created_directly(self):
        plugin = PolarsSupport()
        assert plugin.name == "jupyter-storage-explorer-polars-support"
        assert plugin.version == version("jupyter-storage-explorer-polars-support")

    def test_of_no_package(self, installed):
        # A class of no installed package, e.g. defined in a notebook.
        installed(**{"sample-support": "SampleSupport"})
        [plugin], _ = load_plugins()
        assert (plugin.name, plugin.description, plugin.version) == (None, None, None)


class TestLoading:
    def test_all_by_key(self, installed):
        installed(
            **{"sample-support": "SampleSupport", "other-support": "OtherSupport"}
        )
        plugins, problems = load_plugins()
        assert keys(plugins) == ["other-support", "sample-support"]
        assert problems == []
        # Created with their options' defaults.
        assert plugins[1].options == SampleSupportOptions()
        assert plugins[1].options.priority == LOWEST_PRIORITY

    def test_options(self, installed):
        installed(**{"sample-support": "SampleSupport"})
        [plugin], _ = load_plugins({"sample-support": {"concurrency": 8}})
        assert plugin.options == SampleSupportOptions(concurrency=8)
        # Its properties make its components with them.
        [operations] = plugin.filesystem_operations
        assert operations.concurrency == 8

    def test_disabled_not_imported(self, installed):
        # A broken plugin disabled is no problem: it is not imported.
        installed(**{"sample-support": "SampleSupport", "broken-support": "Missing"})
        plugins, problems = load_plugins({"broken-support": {"enabled": False}})
        assert keys(plugins) == ["sample-support"]
        assert problems == []

    def test_opt_in(self, installed):
        # A plugin whose options' default is disabled.
        installed(**{"opt-in-support": "OptInSupport"})
        assert load_plugins() == ([], [])
        [plugin], _ = load_plugins({"opt-in-support": {"enabled": True}})
        assert plugin.key == "opt-in-support"

    def test_priority_then_key(self, installed):
        installed(
            **{
                "sample-support": "SampleSupport",
                "other-support": "OtherSupport",
                "opt-in-support": "OptInSupport",
            }
        )
        plugins, _ = load_plugins(
            {
                "sample-support": {"priority": 10},
                "opt-in-support": {"enabled": True, "priority": 0},
            }
        )
        assert keys(plugins) == ["sample-support", "opt-in-support", "other-support"]

    def test_options_of_a_plugin_not_installed(self, installed):
        # Shared settings may name plugins an environment lacks: a warning.
        installed(**{"sample-support": "SampleSupport"})
        plugins, problems = load_plugins({"duckdb-support": {"enabled": False}})
        assert keys(plugins) == ["sample-support"]
        assert problems == ["plugin_options: plugin 'duckdb-support' is not installed"]

    def test_unknown_option(self, installed):
        installed(**{"sample-support": "SampleSupport"})
        with pytest.raises(
            ValueError,
            match=r"plugin_options\['sample-support'\]: unknown options \['concurency'\]",
        ):
            load_plugins({"sample-support": {"concurency": 8}})

    @pytest.mark.parametrize(
        ("target", "problem"),
        [
            ("Missing", "AttributeError"),
            ("NotAPlugin", "is no StorageExplorerPlugin"),
            ("WrongKey", "its class's key is 'another-key'"),
            ("FailingSupport", "RuntimeError: cannot start"),
        ],
    )
    def test_left_out_with_the_reason(self, installed, target, problem):
        installed(**{"broken-support": target, "sample-support": "SampleSupport"})
        plugins, problems = load_plugins()
        assert keys(plugins) == ["sample-support"]  # the others are loaded
        [reason] = problems
        assert reason.startswith("plugin 'broken-support' not loaded")
        assert problem in reason

    def test_one_key_registered_twice(self, monkeypatch):
        points = [entry_point("sample-support", "SampleSupport")] * 2
        monkeypatch.setattr(_plugins, "entry_points", lambda group: points)
        plugins, [problem] = load_plugins()
        assert plugins == []
        assert "registered by" in problem


class TestExplorer:
    def test_components_after_those_given_before_the_defaults(self, installed, memfs):
        installed(**{"sample-support": "SampleSupport"})
        given = FsspecOperations()
        mapper = SampleMapper()
        explorer = make(
            "/",
            fs=memfs,
            operations=[given],
            filesystem_mappers=[mapper],
            plugin_options={"sample-support": {"concurrency": 2}},
        )
        operations = explorer._operations.operations
        assert operations[0] is given
        assert type(operations[1]) is SampleOperations
        assert operations[1].concurrency == 2  # with the plugin's options
        mappers = explorer._mappers.mappers
        assert mappers[0] is mapper
        assert type(mappers[1]) is SampleMapper  # a class, created
        assert isinstance(explorer._supports.supports[0], AvroBySample)
        # Its format is detected, and its engine (no view) not offered.
        assert explorer._formats[0].name == "avro"
        assert explorer._engines == []
        assert isinstance(explorer._plugins[0], SampleSupport)

    def test_no_plugin(self, memfs):
        explorer = make("/", fs=memfs, plugin_options=NO_PLUGINS)
        # No engine to choose; the standard formats are detected all the same.
        assert explorer._engines == []
        assert {"parquet", "delta", "csv"} <= set(explorer._format_labels)

    def test_some_disabled(self, memfs):
        explorer = make(
            "/",
            fs=memfs,
            plugin_options={
                "polars-support": {"enabled": False},
                "pyspark-support": {"enabled": False},
            },
        )
        assert [e["key"] for e in explorer._engines] == ["pandas"]

    def test_problems_warn(self, installed, memfs):
        installed(**{"broken-support": "Missing", "sample-support": "SampleSupport"})
        with pytest.warns(RuntimeWarning, match="plugin 'broken-support' not loaded"):
            explorer = make("/", fs=memfs)
        assert explorer._formats[0].name == "avro"  # the others are used

    def test_options_of_a_plugin_not_installed_warn(self, memfs):
        with pytest.warns(RuntimeWarning, match="'polars' is not installed"):
            make("/", fs=memfs, plugin_options={"polars": {"enabled": False}})


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


def test_options_model():
    assert StorageExplorerPluginOptions.option_names() == {"enabled", "priority"}
    assert SampleSupportOptions.option_names() == {"enabled", "priority", "concurrency"}
