"""Plugins for tests/test_plugins.py, loaded through fake entry points."""

from __future__ import annotations

from jupyter_storage_explorer import StorageExplorerPlugin
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
    pass


class SampleMapper(FileSystemMapper):
    classes = ("sample.SampleFileSystem",)


class SampleSupport(StorageExplorerPlugin):
    key = "sample-support"
    label = "Sample support for Storage Explorer"
    format_supports = (AvroBySample,)
    filesystem_operations = (SampleOperations,)
    filesystem_mappers = (SampleMapper,)


class OtherSupport(StorageExplorerPlugin):
    key = "other-support"
    label = "Other support for Storage Explorer"


class WrongKey(StorageExplorerPlugin):
    key = "another-key"
    label = "Wrong key"


class NotAPlugin:
    key = "not-a-plugin"
