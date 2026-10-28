"""Plugins for tests/extensions/test_plugins.py, loaded through fake entry points."""

from __future__ import annotations

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer.actions import ActionOptions, code, register_actions
from jupyter_storage_explorer.engine import Engine
from jupyter_storage_explorer.filesystems import FileSystemMapper
from jupyter_storage_explorer.filesystems.operations import FsspecOperations
from jupyter_storage_explorer.formats import Csv


class AvroFormat(Csv):
    name = "avro"
    label = "Avro"
    extensions = (".avro",)


class SampleEngine(Engine):
    key = "sample"
    label = "Sample"


@dataclass(frozen=True, kw_only=True)
class SampleOptions(ActionOptions):
    region: str | None = None
    account: str | None = None


@code(format=AvroFormat, engine=SampleEngine, label="Load")
def avro_code(fmt, ctx, options: SampleOptions):
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
class LakeSupportOptions(StorageExplorerPluginOptions):
    region: str = "north"


class LakeSupport(StorageExplorerPlugin):
    """Engine options for another plugin's engine, from its own options, as
    a company's plugin gives them."""

    key = "lake-support"
    options_model = LakeSupportOptions

    @property
    def engine_options(self):
        return {"sample": {"*": {"region": self.options.region, "account": "lake"}}}


class FarLakeSupport(StorageExplorerPlugin):
    """Options for SampleSupport's engine, and for an engine not installed."""

    key = "far-lake-support"

    @property
    def engine_options(self):
        return {
            "sample": {"avro": {"region": "far"}},
            "nowhere": {"*": {"region": "far"}},
        }


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


# For check_plugin (tests/test_testing.py): plugins broken in ways explorers
# only log, or fail on.


class SampleEngineAgain(Engine):
    """Another engine class of SampleEngine's key."""

    key = "sample"
    label = "Sample again"


@code(format=Csv, engine=SampleEngineAgain, label="Load again")
def csv_code_again(fmt, ctx, options):
    return "again"


class ClashingSupport(StorageExplorerPlugin):
    """Fine alone, but not with SampleSupport: one engine key, two classes."""

    key = "clashing-support"

    @property
    def actions(self):
        return register_actions(csv_code_again)


@dataclass(frozen=True)
class PositionalOptions(StorageExplorerPluginOptions):
    concurrency: int = 4


class PositionalOptionsSupport(StorageExplorerPlugin):
    key = "positional-support"
    options_model = PositionalOptions


class FailingMapper(FileSystemMapper):
    def __init__(self) -> None:
        raise RuntimeError("needs arguments")


class BrokenComponentsSupport(StorageExplorerPlugin):
    key = "broken-components-support"

    @property
    def actions(self):
        return (avro_code, "not an action")

    @property
    def formats(self):
        return (Csv(),)  # an object, not the class

    @property
    def filesystem_operations(self):
        return (FsspecOperations, object())

    @property
    def filesystem_mappers(self):
        return (FailingMapper,)


class UndecoratedOptions(SampleSupportOptions):
    """Not a dataclass of its own: its field is an ordinary attribute."""

    commits: bool = True


class UndecoratedOptionsSupport(StorageExplorerPlugin):
    key = "undecorated-support"
    options_model = UndecoratedOptions

    @property
    def filesystem_operations(self):
        raise AttributeError("'UndecoratedOptions' object has no attribute 'x'")
