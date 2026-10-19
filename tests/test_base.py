"""What formats share (formats/format.py, requirement.py, base.py): targets,
generated-code helpers, requirements, detection and file icons."""

from __future__ import annotations

import polars
import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import (
    FILE_ICONS,
    Csv,
    DeltaLake,
    Parquet,
    Requirement,
    Text,
    default_formats,
    detect,
    format_kwargs,
    matching_formats,
    snippet_options,
    spark_url,
)
from jupyter_storage_explorer.formats.requirements import Polars
from jupyter_storage_explorer.formats.utils import format_icons


class TestTarget:
    def test_file_properties(self, make_target):
        target = make_target("/dir/data.csv", b"a,b\n1,2\n")
        assert target.name == "data.csv"
        assert not target.is_dir
        assert target.size == 8

    def test_directory_properties(self, make_target, memfs):
        memfs.pipe_file("/table/_delta_log/0.json", b"{}")
        memfs.pipe_file("/table/part-0.parquet", b"")
        target = make_target("/table")
        assert target.is_dir
        assert target.child_names == {"_delta_log", "part-0.parquet"}
        assert target.child_path("x") == "/table/x"

    def test_head_text_whole_file(self, make_target):
        assert make_target("/a.txt", b"one\ntwo\n").head_text(100) == (
            "one\ntwo\n",
            False,
        )

    def test_head_text_cut_after_last_complete_line(self, make_target):
        text, truncated = make_target("/a.txt", b"one\ntwo\nthree\n").head_text(10)
        assert (text, truncated) == ("one\ntwo\n", True)

    def test_head_text_drops_bom(self, make_target):
        assert make_target("/a.txt", b"\xef\xbb\xbfhi").head_text(100)[0] == "hi"


def test_format_kwargs_leaves_out_none():
    assert format_kwargs(sep=";", storage_options=None) == ", sep=';'"
    assert format_kwargs(storage_options=None) == ""


def test_spark_url():
    assert spark_url("s3://bucket/x") == "s3a://bucket/x"
    assert (
        spark_url("abfs://c@a.dfs.core.windows.net/x")
        == "abfss://c@a.dfs.core.windows.net/x"
    )
    assert spark_url("az://c/x") == "abfss://c/x"
    assert spark_url("gs://bucket/x") == "gs://bucket/x"
    assert spark_url("/local/path") == "/local/path"


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
    def test_highest_priority_wins(self, make_target, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        memfs.pipe_file("/t/part-0.parquet", b"")
        target = make_target("/t")
        formats = [Parquet(), DeltaLake()]
        assert isinstance(detect(target, formats), DeltaLake)
        assert [type(f) for f in matching_formats(target, formats)] == [
            DeltaLake,
            Parquet,
        ]

    def test_fallback_to_text(self, make_target):
        target = make_target("/a.csv", b"a,b\n")
        assert [type(f) for f in matching_formats(target, [Text(), Csv()])] == [
            Csv,
            Text,
        ]

    def test_unknown(self, make_target):
        assert detect(make_target("/a.bin", b"\0"), [Text(), Csv()]) is None


@pytest.mark.parametrize("name", ["DATA.CSV", "data.tsv"])
def test_extensions_ignore_case(make_target, name):
    assert Csv().matches(make_target(f"/{name}", b"a\n"))


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
