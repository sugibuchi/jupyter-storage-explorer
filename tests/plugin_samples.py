"""Plugins for tests/extensions/test_plugins.py, loaded through fake entry points."""

from __future__ import annotations

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer.filesystems import FileSystemMapper, FsspecOperations
from jupyter_storage_explorer.formats import Csv, Engine
from jupyter_storage_explorer.formats.actions import code, register_actions


class AvroFormat(Csv):
    name = "avro"
    label = "Avro"
    extensions = (".avro",)


class SampleEngine(Engine):
    key = "sample"
    label = "Sample"


@code(format=AvroFormat, engine=SampleEngine, label="Load")
def avro_code(fmt, ctx, options):
    return "sample"


class SampleOperations(FsspecOperations):
    def __init__(self, concurrency: int = 1) -> None:
        self.concurrency = concurrency


class SampleMapper(FileSystemMapper):
    classes = ("sample.SampleFileSystem",)


@dataclass(frozen=True, kw_only=True)
class SampleSupportOptions(StorageExplorerPluginOptions):
    concurrency: int = 4


class SampleSupport(StorageExplorerPlugin):
    key = "sample-support"
    options_model = SampleSupportOptions

    @property
    def actions(self):
        return register_actions(avro_code)

    @property
    def filesystem_operations(self):
        # Made with the plugin's options.
        return (SampleOperations(concurrency=self.options.concurrency),)

    @property
    def filesystem_mappers(self):
        return (SampleMapper,)  # a class: the explorer creates it


class OtherSupport(StorageExplorerPlugin):
    key = "other-support"


@dataclass(frozen=True, kw_only=True)
class OptInOptions(StorageExplorerPluginOptions):
    enabled: bool = False


class OptInSupport(StorageExplorerPlugin):
    """Off unless enabled: its options' default."""

    key = "opt-in-support"
    options_model = OptInOptions


class FailingSupport(StorageExplorerPlugin):
    key = "broken-support"  # the entry point's name in the tests

    def __init__(self, options=None) -> None:
        raise RuntimeError("cannot start")


class WrongKey(StorageExplorerPlugin):
    key = "another-key"


class NotAPlugin:
    key = "not-a-plugin"
