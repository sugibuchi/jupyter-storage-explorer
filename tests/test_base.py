"""What formats share (formats/base.py, requirement.py): reading files,
generated-code helpers, requirements, detection and file icons (the
supports: test_supports.py)."""

from __future__ import annotations

import polars
import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems import LocalLocation, S3Location
from jupyter_storage_explorer.formats import (
    FILE_ICONS,
    Csv,
    DeltaLake,
    Parquet,
    PreviewLimits,
    Requirement,
    Text,
    child_names,
    default_formats,
    detect,
    file_size,
    format_kwargs,
    head_text,
    library_url,
    matching_formats,
    name_of,
    read_whole,
    snippet_options,
)
from jupyter_storage_explorer.formats.requirements import Polars
from jupyter_storage_explorer.formats.utils import format_icons


class TestReading:
    """Reading a file through its filesystem, for detection and previews."""

    def test_names_and_sizes(self, memfs):
        memfs.pipe_file("/dir/data.csv", b"a,b\n1,2\n")
        assert name_of("/dir/data.csv") == "data.csv"
        assert name_of("/dir/") == "dir"
        assert file_size(memfs, "/dir/data.csv") == 8

    def test_child_names(self, memfs):
        memfs.pipe_file("/table/_delta_log/0.json", b"{}")
        memfs.pipe_file("/table/part-0.parquet", b"")
        children = memfs.ls("/table", detail=True)
        assert child_names(children) == {"_delta_log", "part-0.parquet"}
        assert child_names(None) == set()

    def test_head_text_whole_file(self, memfs):
        memfs.pipe_file("/a.txt", b"one\ntwo\n")
        assert head_text(memfs, "/a.txt", 100) == ("one\ntwo\n", False)

    def test_head_text_cut_after_last_complete_line(self, memfs):
        memfs.pipe_file("/a.txt", b"one\ntwo\nthree\n")
        assert head_text(memfs, "/a.txt", 10) == ("one\ntwo\n", True)

    def test_head_text_drops_bom(self, memfs):
        memfs.pipe_file("/a.txt", b"\xef\xbb\xbfhi")
        assert head_text(memfs, "/a.txt", 100)[0] == "hi"

    def test_read_whole_within_the_limit(self, memfs):
        memfs.pipe_file("/a.bin", b"x" * 10)
        assert read_whole(memfs, "/a.bin", PreviewLimits()) == b"x" * 10
        with pytest.raises(ValueError, match="too large to preview"):
            read_whole(memfs, "/a.bin", PreviewLimits(max_whole_file_bytes=5))


def test_library_url(tmp_path):
    local = LocalLocation(path=tmp_path.as_posix(), hostname="h")
    assert library_url(local) == tmp_path.as_posix()  # polars and pandas take it
    assert library_url(S3Location(bucket="b", key="k")) == "s3://b/k"


def test_format_kwargs_leaves_out_none():
    assert format_kwargs(sep=";", storage_options=None) == ", sep=';'"
    assert format_kwargs(storage_options=None) == ""


class TestSnippetOptions:
    def test_none(self):
        assert snippet_options(None) == {}

    def test_drops_secrets_and_objects(self):
        options = {
            "anon": True,
            "account_key": "k",
            "SAS_TOKEN": "t",
            "password": "p",
            "fs": object(),
            "region": "eu",
        }
        assert snippet_options(options) == {"anon": True, "region": "eu"}

    def test_nested_mappings_filtered_key_by_key(self):
        options = {
            "client_kwargs": {"endpoint_url": "http://x", "aws_secret_access_key": "s"}
        }
        assert snippet_options(options) == {
            "client_kwargs": {"endpoint_url": "http://x"}
        }


class TestRequirement:
    def test_installed_and_loaded(self):
        assert Polars().is_installed()
        assert Polars().load() is polars

    def test_missing(self):
        missing = type(
            "Missing", (Requirement,), {"package": "x", "import_name": "not_a_pkg"}
        )
        assert not missing().is_installed()


class TestDetection:
    def test_highest_priority_wins(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        memfs.pipe_file("/t/part-0.parquet", b"")
        item = make_item("/t")
        formats = [Parquet(), DeltaLake()]
        assert isinstance(detect(*item.match_args, formats=formats), DeltaLake)
        assert [
            type(f) for f in matching_formats(*item.match_args, formats=formats)
        ] == [
            DeltaLake,
            Parquet,
        ]

    def test_fallback_to_text(self, make_item):
        item = make_item("/a.csv", b"a,b\n")
        assert [
            type(f) for f in matching_formats(*item.match_args, formats=[Text(), Csv()])
        ] == [
            Csv,
            Text,
        ]

    def test_unknown(self, make_item):
        assert (
            detect(*make_item("/a.bin", b"\0").match_args, formats=[Text(), Csv()])
            is None
        )


@pytest.mark.parametrize("name", ["DATA.CSV", "data.tsv"])
def test_extensions_ignore_case(make_item, name):
    assert Csv().matches(*make_item(f"/{name}", b"a\n").match_args)


class TestFileIcons:
    """Each format's file_icon, sent to the frontend by format name; files of
    formats without one get their extension's icon there (icons.js)."""

    SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>'

    def avro(self, icon):
        return type("Avro", (Csv,), {"name": "avro", "file_icon": icon})()

    def test_default_formats(self):
        assert format_icons(default_formats()) == (
            {
                "parquet": "spreadsheet",
                "csv": "spreadsheet",
                "excel": "spreadsheet",
                "json": "json",
                "json-lines": "json",
                "markdown": "markdown",
                "image": "image",
            },  # not Text (Python, YAML, ... by extension), nor Delta (folders)
            {},
        )

    def test_one_of_jupyterlabs(self):
        explorer = StorageExplorer(fs=None, formats=[self.avro("file"), Text()])
        assert explorer._format_icons == {"avro": "file"}
        assert explorer._file_icon_svgs == {}

    def test_own_svg(self):
        explorer = StorageExplorer(fs=None, formats=[self.avro(("avro", self.SVG))])
        assert explorer._format_icons == {"avro": "avro"}
        assert explorer._file_icon_svgs == {"avro": self.SVG}

    @pytest.mark.parametrize(
        ("icon", "error"),
        [
            ("avro", "unknown file_icon of format 'avro': 'avro'"),
            (("json", SVG), "name it other than"),
            (("avro", "<div/>"), "not SVG markup"),
        ],
    )
    def test_invalid(self, icon, error):
        assert "spreadsheet" in FILE_ICONS
        with pytest.raises(ValueError, match=error):
            format_icons([self.avro(icon)])

    def test_one_name_per_svg(self):
        other = type("Orc", (Csv,), {"name": "orc", "file_icon": ("avro", "<svg/>")})
        with pytest.raises(ValueError, match="another icon is named 'avro'"):
            format_icons([self.avro(("avro", self.SVG)), other()])
