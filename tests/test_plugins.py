"""Plugins (plugin.py, _plugins.py): which are loaded, with which options,
what they give the explorer, and in which order."""

from __future__ import annotations

import email.message
from importlib.metadata import EntryPoint, version

import pytest
from all_actions import NO_PLUGINS, PLUGINS
from explorers import make
from jupyter_storage_explorer_polars_support import PolarsSupport
from plugin_samples import (
    SampleEngine,
    SampleMapper,
    SampleOperations,
    SampleSupport,
    SampleSupportOptions,
    avro_code,
)

from jupyter_storage_explorer import _plugins
from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer._plugins import load_plugins
from jupyter_storage_explorer.filesystems import FsspecOperations
from jupyter_storage_explorer.formats import Csv, Engine
from jupyter_storage_explorer.formats.actions import code
from jupyter_storage_explorer.plugin import (
    ENTRY_POINT_GROUP,
    LOWEST_PRIORITY,
    StorageExplorerPluginOptions,
    homepage,
    package_authors,
    package_license,
    package_urls,
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
        "dask-support",
        "databricks-support",
        "duckdb-support",
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

    def test_authors_license_and_links(self):
        for plugin in PLUGINS:
            assert plugin.authors == ["Tsuyoshi SUGIBUCHI"]
            assert plugin.license == "MIT"
            assert plugin.urls["Homepage"].endswith(f"/plugins/{plugin.key}")
            assert "Issues" in plugin.urls

    def test_of_no_package(self, installed):
        # A class of no installed package, e.g. defined in a notebook.
        installed(**{"sample-support": "SampleSupport"})
        [plugin], _ = load_plugins()
        assert (plugin.name, plugin.description, plugin.version) == (None, None, None)
        assert (plugin.authors, plugin.license, plugin.urls) == ([], None, {})


class FakeDistribution:
    """A package's metadata, as importlib.metadata gives it."""

    def __init__(self, **fields):
        self.metadata = email.message.Message()
        for name, values in fields.items():
            for value in values if isinstance(values, list) else [values]:
                self.metadata[name.replace("_", "-")] = value


class TestPackageMetadata:
    """How authors, licenses and links are read from any package's metadata."""

    def test_authors_by_name_once(self):
        dist = FakeDistribution(
            Author="Ann, Bob",
            Author_email='Bob <bob@x.org>, "Carl C" <carl@x.org>, only@x.org',
            Maintainer_email="Dee <dee@x.org>",
        )
        assert package_authors(dist) == ["Ann", "Bob", "Carl C", "Dee"]
        assert package_authors(FakeDistribution()) == []

    @pytest.mark.parametrize(
        ("fields", "license"),
        [
            ({"License_Expression": "MIT OR Apache-2.0"}, "MIT OR Apache-2.0"),
            ({"License": "BSD-3-Clause"}, "BSD-3-Clause"),
            ({"License": "Copyright (c) 2026\n\nPermission is hereby..."}, None),
            ({}, None),
        ],
    )
    def test_license(self, fields, license):
        assert package_license(FakeDistribution(**fields)) == license

    def test_links_http_only(self):
        dist = FakeDistribution(
            Home_page="https://old.example.org",
            Project_URL=[
                "Homepage, https://example.org",
                "Source, http://git.example.org/x",
                "Evil, javascript:alert(1)",
                "Docs, file:///etc/passwd",
            ],
        )
        urls = package_urls(dist)
        assert urls == {
            "Homepage": "https://old.example.org",  # the legacy field first
            "Source": "http://git.example.org/x",
        }

    @pytest.mark.parametrize(
        ("urls", "home"),
        [
            ({"Issues": "https://i", "Repository": "https://r"}, "https://r"),
            ({"homepage": "https://h", "Source": "https://s"}, "https://h"),
            ({"Issues": "https://i"}, None),
        ],
    )
    def test_homepage(self, urls, home):
        assert homepage(urls) == home


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
        plugins, problems = load_plugins({"sqlite-support": {"enabled": False}})
        assert keys(plugins) == ["sample-support"]
        assert problems == ["plugin_options: plugin 'sqlite-support' is not installed"]

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
        assert explorer._actions.actions[0] is avro_code
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
                "dask-support": {"enabled": False},
                "duckdb-support": {"enabled": False},
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

    def csv_code(engine):
        @code(format=Csv, engine=engine, label="Load CSV")
        def loading(fmt, ctx, options):
            return ""

        return loading

    with pytest.raises(ValueError, match="engine 'sample' is defined twice"):
        ActionChain([avro_code, csv_code(copy)])
    # The same class, imported: fine.
    assert ActionChain([avro_code, csv_code(SampleEngine)]).actions


def test_options_model():
    assert StorageExplorerPluginOptions.option_names() == {"enabled", "priority"}
    assert SampleSupportOptions.option_names() == {"enabled", "priority", "concurrency"}
