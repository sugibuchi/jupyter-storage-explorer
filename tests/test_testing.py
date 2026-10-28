"""testing.py's check_plugin: a plugin checked as explorers load it, on the
sample plugins of plugin_samples.py, through fake entry points."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest
from plugin_samples import SampleOperations, SampleSupport

from jupyter_storage_explorer._extensions import plugins as _plugins
from jupyter_storage_explorer.plugin import ENTRY_POINT_GROUP, StorageExplorerPlugin
from jupyter_storage_explorer.testing import check_plugin


@pytest.fixture
def installed(monkeypatch):
    """Fake the plugins installed, by name, each with a description: those
    of fake entry points have no package to read it from."""
    monkeypatch.setattr(
        StorageExplorerPlugin,
        "description",
        property(lambda self: f"{self.key} for Storage Explorer"),
    )

    def install(**targets):
        points = [
            EntryPoint(name, f"plugin_samples:{target}", ENTRY_POINT_GROUP)
            for name, target in targets.items()
        ]
        monkeypatch.setattr(_plugins, "entry_points", lambda group: points)

    return install


def test_the_repository_plugins():
    for key in ["abfs-support", "duckdb-support", "polars-support"]:
        assert check_plugin(key).key == key


def test_a_plugin_with_its_options(installed):
    installed(**{"sample-support": "SampleSupport"})
    plugin = check_plugin("sample-support", {"concurrency": 8})
    assert isinstance(plugin, SampleSupport)
    [operations] = plugin.filesystem_operations
    assert isinstance(operations, SampleOperations)
    assert operations.concurrency == 8


def test_an_unknown_option(installed):
    installed(**{"sample-support": "SampleSupport"})
    with pytest.raises(ValueError, match=r"unknown options \['concurency'\]"):
        check_plugin("sample-support", {"concurency": 8})


def test_not_installed(installed):
    installed()
    with pytest.raises(AssertionError, match="no plugin 'sample-support' installed"):
        check_plugin("sample-support")


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("Missing", "not loaded: AttributeError"),
        ("WrongKey", "its class's key is 'another-key'"),
        ("NotAPlugin", "is no StorageExplorerPlugin"),
        ("FailingSupport", "not loaded: RuntimeError: cannot start"),
    ],
)
def test_what_explorers_leave_out(installed, target, message):
    # Explorers only warn about these: the check fails.
    installed(**{"broken-support": target})
    with pytest.raises(AssertionError, match=message):
        check_plugin("broken-support")


def test_registered_twice(installed, monkeypatch):
    point = EntryPoint(
        "sample-support", "plugin_samples:SampleSupport", ENTRY_POINT_GROUP
    )
    monkeypatch.setattr(_plugins, "entry_points", lambda group: [point, point])
    with pytest.raises(AssertionError, match="registered by"):
        check_plugin("sample-support")


def test_options_model(installed):
    installed(**{"positional-support": "PositionalOptionsSupport"})
    with pytest.raises(AssertionError, match=r"frozen=True, kw_only=True"):
        check_plugin("positional-support")


def test_no_description(monkeypatch):
    point = EntryPoint(
        "sample-support", "plugin_samples:SampleSupport", ENTRY_POINT_GROUP
    )
    monkeypatch.setattr(_plugins, "entry_points", lambda group: [point])
    with pytest.raises(AssertionError, match="its package has no description"):
        check_plugin("sample-support")


def test_every_broken_component_named(installed):
    installed(**{"broken-components-support": "BrokenComponentsSupport"})
    with pytest.raises(AssertionError) as raised:
        check_plugin("broken-components-support")
    message = str(raised.value)
    assert "actions: 'not an action' is no action" in message
    assert "formats: <" in message and "is no DataFormat class" in message
    assert "filesystem_operations: <object object" in message
    assert "is no FileSystemOperations" in message
    assert "filesystem_mappers: FailingMapper() fails: RuntimeError" in message


def test_with_the_other_plugins(installed):
    # Each loads alone; an explorer with both would fail: one engine key,
    # two classes.
    installed(**{"clashing-support": "ClashingSupport"})
    check_plugin("clashing-support")
    installed(
        **{"sample-support": "SampleSupport", "clashing-support": "ClashingSupport"}
    )
    with pytest.raises(AssertionError, match=r"other plugins' \(sample-support\)"):
        check_plugin("clashing-support")
