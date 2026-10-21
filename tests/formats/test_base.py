"""What formats share (formats/base.py, package.py): reading files
(ItemContext), generated-code helpers, requirements and detection, with
signatures (the supports: test_supports.py; the formats' file icons:
explorer/test_explorer_icons.py)."""

from __future__ import annotations

import dataclasses

import fsspec
import pytest
from format_samples import DUCKDB_BYTES, SQLITE_BYTES, DuckDB, SQLite
from items import local_item

from jupyter_storage_explorer.filesystems import S3Location
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    ItemContext,
    Parquet,
    PythonPackage,
    SupportOptions,
    Text,
    ViewLimits,
    format_kwargs,
)
from jupyter_storage_explorer.formats.base import detect, matching_formats
from jupyter_storage_explorer.formats.packages import Fsspec


class TestReading:
    """Reading a file through its filesystem, for detection and previews
    (``ItemContext``)."""

    def test_names_and_sizes(self, make_item):
        item = make_item("/dir/data.csv", b"a,b\n1,2\n")
        assert (item.name, item.size, item.is_dir) == ("data.csv", 8, False)
        assert make_item("/dir").name == "dir"

    def test_child_names(self, make_item, memfs):
        memfs.pipe_file("/table/_delta_log/0.json", b"{}")
        memfs.pipe_file("/table/part-0.parquet", b"")
        assert make_item("/table").child_names == {"_delta_log", "part-0.parquet"}
        assert make_item("/table/part-0.parquet").child_names == set()

    def test_head_text_whole_file(self, make_item):
        item = make_item("/a.txt", b"one\ntwo\n")
        assert item.head_text(100) == ("one\ntwo\n", False)
        assert item.head(3) == b"one"

    def test_head_text_cut_after_last_complete_line(self, make_item):
        item = make_item("/a.txt", b"one\ntwo\nthree\n")
        assert item.head_text(10) == ("one\ntwo\n", True)

    def test_head_text_drops_bom(self, make_item):
        assert make_item("/a.txt", b"\xef\xbb\xbfhi").head_text(100)[0] == "hi"

    def test_read_whole_within_the_limit(self, make_item):
        item = make_item("/a.bin", b"x" * 10)
        assert item.read_whole(ViewLimits()) == b"x" * 10
        with pytest.raises(ValueError, match="too large to view"):
            item.read_whole(ViewLimits(max_whole_file_bytes=5))


def test_library_url(tmp_path, make_item):
    local = local_item(tmp_path)
    assert local.library_url == tmp_path.as_posix()  # polars and pandas take it
    s3 = make_item("/k", b"", location=S3Location(bucket="b", key="k"))
    assert s3.library_url == "s3://b/k"


def test_format_kwargs_leaves_out_none():
    assert format_kwargs(sep=";", storage_options=None) == ", sep=';'"
    assert format_kwargs(storage_options=None) == ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class StorageOptions(SupportOptions):
    storage_options: dict | None = None


class TestCodeValue:
    """Options as generated code shows them, without declared secrets (see
    test_supports.py's TestSecrets): names that look like credentials and
    objects are left out anyway."""

    def test_none(self):
        assert StorageOptions().code_value("storage_options") is None

    def test_drops_secrets_and_objects(self):
        options = StorageOptions(
            storage_options={
                "anon": True,
                "account_key": "k",
                "SAS_TOKEN": "t",
                "password": "p",
                "fs": object(),
                "region": "eu",
            }
        )
        assert options.code_value("storage_options") == {"anon": True, "region": "eu"}

    def test_nested_mappings_filtered_key_by_key(self):
        options = StorageOptions(
            storage_options={
                "client_kwargs": {
                    "endpoint_url": "http://x",
                    "aws_secret_access_key": "s",
                }
            }
        )
        assert options.code_value("storage_options") == {
            "client_kwargs": {"endpoint_url": "http://x"}
        }


class TestRequirement:
    def test_installed_and_loaded(self):
        assert Fsspec().is_installed()
        assert Fsspec().load() is fsspec

    def test_missing(self):
        missing = type(
            "Missing", (PythonPackage,), {"package": "x", "import_name": "not_a_pkg"}
        )
        assert not missing().is_installed()


class TestDetection:
    def test_highest_priority_wins(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        memfs.pipe_file("/t/part-0.parquet", b"")
        item = make_item("/t")
        formats = [Parquet(), DeltaLake()]
        assert isinstance(detect(item, formats=formats), DeltaLake)
        assert [type(f) for f in matching_formats(item, formats=formats)] == [
            DeltaLake,
            Parquet,
        ]

    def test_fallback_to_text(self, make_item):
        item = make_item("/a.csv", b"a,b\n")
        assert [type(f) for f in matching_formats(item, formats=[Text(), Csv()])] == [
            Csv,
            Text,
        ]

    def test_unknown(self, make_item):
        assert detect(make_item("/a.bin", b"\0"), formats=[Text(), Csv()]) is None


class TestSniffing:
    """Formats confirmed by a file's first bytes (``DataFormat.sniff``):
    always, whichever formats are installed, but never in listings."""

    @pytest.fixture
    def reads(self, monkeypatch):
        """The sizes ``ItemContext.head`` was asked for."""
        sizes = []
        head = ItemContext.head

        def counted(self, size):
            sizes.append(size)
            return head(self, size)

        monkeypatch.setattr(ItemContext, "head", counted)
        return sizes

    @pytest.mark.parametrize(
        ("data", "expected"), [(SQLITE_BYTES, SQLite), (DUCKDB_BYTES, DuckDB)]
    )
    def test_signature_decides_a_shared_extension(
        self, make_item, reads, data, expected
    ):
        item = make_item("/x.db", data)
        assert type(detect(item, formats=[SQLite(), DuckDB()])) is expected
        assert [
            type(f) for f in matching_formats(item, formats=[SQLite(), DuckDB()])
        ] == [expected]
        # Read once per detection, as much as the most demanding format asks.
        assert reads == [16, 16]

    def test_checked_even_when_one_format_claims_it(self, make_item):
        # Installing only a SQLite plugin says nothing of the lake's files.
        item = make_item("/x.db", DUCKDB_BYTES)
        assert detect(item, formats=[SQLite()]) is None
        assert matching_formats(item, formats=[SQLite()]) == []

    def test_short_file(self, make_item):
        assert detect(make_item("/x.db", b"SQL"), formats=[SQLite(), DuckDB()]) is None

    def test_unreadable_file_confirms_nothing(self, make_item, monkeypatch):
        item = make_item("/x.db", SQLITE_BYTES)

        def fail(self, size):
            raise OSError("denied")

        monkeypatch.setattr(ItemContext, "head", fail)
        assert detect(item, formats=[SQLite(), Csv()]) is None

    def test_other_formats_never_read(self, make_item, reads):
        item = make_item("/a.csv", b"a,b\n")
        assert type(detect(item, formats=[SQLite(), DuckDB(), Csv()])) is Csv
        assert reads == []

    def test_listings_never_read(self, make_item, reads):
        # Undecided, rather than a guess the contents may contradict.
        item = make_item("/x.db", SQLITE_BYTES)
        assert detect(item, formats=[SQLite(), DuckDB()], sniff=False) is None
        csv = make_item("/a.csv", b"a,b\n")
        assert type(detect(csv, formats=[SQLite(), Csv()], sniff=False)) is Csv
        assert reads == []

    def test_folders_never_sniffed(self, make_item, memfs, reads):
        memfs.pipe_file("/d.db/x", b"")

        class Folders(SQLite):
            def matches(self, ctx):
                return ctx.is_dir

        assert type(detect(make_item("/d.db"), formats=[Folders()])) is Folders
        assert reads == []


@pytest.mark.parametrize("name", ["DATA.CSV", "data.tsv"])
def test_extensions_ignore_case(make_item, name):
    assert Csv().matches(make_item(f"/{name}", b"a\n"))
