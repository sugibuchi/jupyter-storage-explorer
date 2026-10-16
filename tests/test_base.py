"""Helpers of formats/base.py: targets, generated-code helpers, requirements and detection."""

from __future__ import annotations

import types

import polars
import pytest

from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Parquet,
    Text,
    detect,
    format_args,
    matching_formats,
)
from jupyter_storage_explorer.formats.base import snippet_options, spark_url
from jupyter_storage_explorer.formats.requirements import Polars


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


def test_format_args_leaves_out_none():
    assert (
        format_args("data.csv", sep=";", storage_options=None) == "'data.csv', sep=';'"
    )


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
    def test_code_name_prefers_imported_name(self):
        assert Polars().code_name({"polars": polars}) == "polars"
        assert Polars().code_name({}) == "pl"

    def test_code_name_skips_names_bound_to_something_else(self):
        assert Polars().get_module_name({"pl": 1}) is None
        assert Polars().get_module_name({"pl": types.ModuleType("other")}) is None

    def test_import_command(self):
        assert Polars().import_command == "import polars as pl"


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
