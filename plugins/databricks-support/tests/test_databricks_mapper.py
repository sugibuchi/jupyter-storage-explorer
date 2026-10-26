"""databricks-support: locations naming the workspace, on a fake of
fsspec-databricks' filesystem (the real one needs a workspace); its entry
point."""

from __future__ import annotations

from importlib.metadata import entry_points
from types import SimpleNamespace

import pytest
from fsspec import AbstractFileSystem
from jupyter_storage_explorer_databricks_support import (
    DatabricksLocation,
    DatabricksSupport,
    DatabricksWorkspaceMapper,
)

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems import MapperChain, default_mappers
from jupyter_storage_explorer.filesystems.locations import FsspecLocation
from jupyter_storage_explorer.filesystems.mappers import DatabricksMapper

HOST = "https://ADB-1234567890123456.7.azuredatabricks.net/"


class DatabricksFileSystem(AbstractFileSystem):
    """As fsspec-databricks' (matched by its qualified name): ``config.host``
    is the workspace's, as the Databricks SDK's configuration gives it."""

    cachable = False  # each test's own instances
    protocol = "dbfs"

    def __init__(self, host=HOST, **kwargs):
        super().__init__(**kwargs)
        self._host = host

    @property
    def config(self):
        return SimpleNamespace(host=self._host)


DatabricksFileSystem.__module__ = "fsspec_databricks.spec"


@pytest.fixture
def chain():
    """The mappers of an explorer with the plugin: its first."""
    return MapperChain([*DatabricksSupport().filesystem_mappers, *default_mappers()])


class TestLocations:
    def test_with_the_workspaces_host(self, chain):
        location = chain.location_of(
            DatabricksFileSystem(), "/Volumes/main/sales/raw/a.csv"
        )
        assert location == DatabricksLocation(
            host="adb-1234567890123456.7.azuredatabricks.net",
            path="/Volumes/main/sales/raw/a.csv",
        )
        # The URL libraries read, as the explorer's own mapper gives it.
        assert location.url == "dbfs://Volumes/main/sales/raw/a.csv"

    @pytest.mark.parametrize(
        ("path", "level"),
        [
            ("", "workspace"),
            ("/Volumes/main", "catalog"),
            ("/Workspace/Repos", "repos"),
        ],
    )
    def test_the_explorers_levels(self, chain, path, level):
        assert chain.level_of(DatabricksFileSystem(), path) == level

    def test_the_explorers_icons(self, chain):
        mapper = chain.mapper_of(DatabricksFileSystem())
        assert mapper.css and mapper.css == DatabricksMapper.css

    def test_the_top(self, chain):
        location = chain.location_of(DatabricksFileSystem(), "")
        assert (location.path, location.url) == ("/", "dbfs://")

    def test_through_json(self, chain):
        location = chain.location_of(DatabricksFileSystem(), "/Workspace/Shared/x.py")
        assert Location.from_json(location.to_json()) == location


class TestWorkspacesToldApart:
    def test_files_of_the_same_workspace(self, chain):
        here, there = DatabricksFileSystem(), DatabricksFileSystem(host=HOST.lower())
        location = chain.location_of(there, "/Volumes/main/s/v/a.csv")
        assert chain.path_in(here, location) == "/Volumes/main/s/v/a.csv"
        assert chain.same_filesystem(here, there)

    def test_files_of_another_workspace(self, chain):
        here = DatabricksFileSystem()
        there = DatabricksFileSystem(host="https://dbc-other.cloud.databricks.com")
        location = chain.location_of(there, "/Volumes/main/s/v/a.csv")
        assert chain.path_in(here, location) is None
        assert not chain.same_filesystem(here, there)

    def test_files_pasted_from_another_kernel_found(self, chain, memfs):
        # A location from JSON, as another kernel's explorer copied it: found
        # on the storage of its workspace among the explorer's.
        location = Location.from_json(
            DatabricksLocation(host=HOST, path="/Volumes/main/s/v/a.csv").to_json()
        )
        fs = DatabricksFileSystem()
        assert chain.locate(location, [memfs, fs]) == (fs, "/Volumes/main/s/v/a.csv")

    def test_fsspecs_urls_still_reached(self, chain):
        # From a kernel without the plugin: the explorer's own form.
        location = FsspecLocation(url="dbfs://Volumes/main/s/v/a.csv")
        assert (
            chain.path_in(DatabricksFileSystem(), location) == "/Volumes/main/s/v/a.csv"
        )


@pytest.mark.parametrize(
    ("given", "host"),
    [
        ("https://ADB-1.azuredatabricks.net/", "adb-1.azuredatabricks.net"),
        ("adb-1.azuredatabricks.net", "adb-1.azuredatabricks.net"),
        ("https://dbc-x.cloud.databricks.com:443/", "dbc-x.cloud.databricks.com"),
    ],
)
def test_hosts_normalized(given, host):
    assert DatabricksLocation(host=given, path="Volumes/x/").host == host
    assert DatabricksLocation(host=given, path="Volumes/x/").path == "/Volumes/x"


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="databricks-support"
    )
    plugin = entry_point.load()()  # loads without fsspec-databricks
    assert isinstance(plugin, DatabricksSupport)
    assert plugin.description == "Databricks support for Storage Explorer"
    [mapper] = plugin.filesystem_mappers
    assert isinstance(mapper, DatabricksWorkspaceMapper)
