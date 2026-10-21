"""Plugins for tests/test_plugins.py, loaded through fake entry points."""

from __future__ import annotations

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer.filesystems import FileSystemMapper, FsspecOperations
from jupyter_storage_explorer.formats import Csv, Engine, FormatSupport


class AvroFormat(Csv):
    name = "avro"
    label = "Avro"
    extensions = (".avro",)


class SampleEngine(Engine):
    key = "sample"
    label = "Sample"


class AvroBySample(FormatSupport):
    format = AvroFormat
    engine = SampleEngine
    capabilities = ("recipe",)

    def recipe(self, fmt, ctx, options):
        return {"Load": "sample"}


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
    label = "Sample support for Storage Explorer"
    options_model = SampleSupportOptions

    @property
    def format_supports(self):
        return (AvroBySample,)

    @property
    def filesystem_operations(self):
        # Made with the plugin's options.
        return (SampleOperations(concurrency=self.options.concurrency),)

    @property
    def filesystem_mappers(self):
        return (SampleMapper,)  # a class: the explorer creates it


class OtherSupport(StorageExplorerPlugin):
    key = "other-support"
    label = "Other support for Storage Explorer"


@dataclass(frozen=True, kw_only=True)
class OptInOptions(StorageExplorerPluginOptions):
    enabled: bool = False


class OptInSupport(StorageExplorerPlugin):
    """Off unless enabled: its options' default."""

    key = "opt-in-support"
    label = "Opt-in support for Storage Explorer"
    options_model = OptInOptions


class FailingSupport(StorageExplorerPlugin):
    key = "broken-support"  # the entry point's name in the tests
    label = "Failing"

    def __init__(self, options=None) -> None:
        raise RuntimeError("cannot start")


class WrongKey(StorageExplorerPlugin):
    key = "another-key"
    label = "Wrong key"


class NotAPlugin:
    key = "not-a-plugin"
