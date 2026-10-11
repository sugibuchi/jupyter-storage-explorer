"""Each default format: detection, previews and the code snippets of its recipes."""

from __future__ import annotations

import io
import json

import pandas as pd
import polars as pl
import pytest

from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Excel,
    Image,
    InstallPreview,
    Json,
    JsonLines,
    Markdown,
    MarkdownPreview,
    MediaPreview,
    Parquet,
    PreviewLimits,
    Requirement,
    TablePreview,
    Target,
    Text,
    TextPreview,
    TreePreview,
)
from jupyter_storage_explorer.formats.requirements import Pillow


def parquet_bytes(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def last_line(code: str) -> str:
    return code.strip().splitlines()[-1]


class TestParquetDetection:
    def test_spark_output(self, make_target, memfs):
        for i in range(3):
            memfs.pipe_file(
                f"/out/part-0000{i}-2e8a686a-d04f-4489-ad50-a834723e6591-c000.snappy.parquet",
                b"",
            )
        memfs.pipe_file("/out/_SUCCESS", b"")
        memfs.pipe_file("/out/.part-00000.crc", b"")
        assert Parquet().matches(make_target("/out"))

    def test_differently_named_tables_are_not_one_dataset(self, make_target, memfs):
        memfs.pipe_file("/d/orders.parquet", b"")
        memfs.pipe_file("/d/customers.parquet", b"")
        assert not Parquet().matches(make_target("/d"))

    def test_folder_with_other_files(self, make_target, memfs):
        memfs.pipe_file("/d/part-0.parquet", b"")
        memfs.pipe_file("/d/readme.md", b"")
        assert not Parquet().matches(make_target("/d"))

    def test_hive_files_checked_by_magic_bytes(self, make_target, memfs):
        memfs.pipe_file("/hive/000000_0", parquet_bytes(pl.DataFrame({"a": [1]})))
        memfs.pipe_file("/hive/000001_0", b"")
        assert Parquet().matches(make_target("/hive"))
        memfs.pipe_file("/orc/000000_0", b"ORC...")
        assert not Parquet().matches(make_target("/orc"))

    def test_partition_folders_are_not_a_dataset(self, make_target, memfs):
        memfs.pipe_file("/t/year=2025/part-0.parquet", b"")
        assert not Parquet().matches(make_target("/t"))


def test_delta_detection(make_target, memfs):
    memfs.pipe_file("/t/_delta_log/0.json", b"{}")
    assert DeltaLake().matches(make_target("/t"))
    memfs.pipe_file("/u/part-0.parquet", b"")
    assert not DeltaLake().matches(make_target("/u"))


class TestPreviews:
    limits = PreviewLimits(max_rows=2)

    def test_csv_detects_separator(self, make_target):
        target = make_target("/a.csv", b"x;y\n1;2\n3;4\n5;6\n")
        [table] = Csv().preview(target, self.limits)
        assert isinstance(table, TablePreview)
        assert table.columns == ["x", "y"]
        assert table.rows == [[1, 2], [3, 4]]

    def test_json_tree(self, make_target):
        [tree] = Json().preview(make_target("/a.json", b'{"a": [1, 2]}'), self.limits)
        assert isinstance(tree, TreePreview)
        assert tree.value == {"a": [1, 2]}

    def test_invalid_json_shown_as_text(self, make_target):
        [text] = Json().preview(make_target("/a.json", b"{oops"), self.limits)
        assert isinstance(text, TextPreview)
        assert text.note.startswith("Invalid JSON")

    def test_json_lines(self, make_target):
        data = b"".join(json.dumps({"i": i}).encode() + b"\n" for i in range(5))
        [table] = JsonLines().preview(make_target("/a.jsonl", data), self.limits)
        assert table.rows == [[0], [1]]

    def test_parquet_file_with_pandas(self, make_target):
        # pyarrow reads through the target's fsspec filesystem, so memory:// works.
        data = parquet_bytes(pl.DataFrame({"a": [1, 2, 3]}))
        target = make_target("/a.parquet", data)
        [table] = Parquet().preview_with_pandas(target, self.limits)
        assert table.rows == [[1], [2]]
        assert "of 3" in table.note

    def test_parquet_file_with_polars(self, tmp_path, memfs):
        # polars reads by URL: a local path.
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1, 2, 3]}).write_parquet(path)
        target = Target(fs=memfs, path=str(path), url=str(path), info={})
        [table] = Parquet().preview_with_polars(target, self.limits)
        assert table.rows == [[1], [2]]
        assert "of 3" in table.note

    def test_excel_first_sheet(self, make_target):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1, 2, 3]}).to_excel(
                writer, sheet_name="one", index=False
            )
            pd.DataFrame({"b": [1]}).to_excel(writer, sheet_name="two", index=False)
        [table] = Excel().preview(
            make_target("/a.xlsx", buffer.getvalue()), self.limits
        )
        assert table.title == "one"
        assert table.rows == [[1], [2]]
        assert "other sheets: two" in table.note

    def test_text_highlighted(self, make_target):
        [text] = Text().preview(make_target("/a.py", b"import os\n"), self.limits)
        assert text.language == "python"
        assert text.html is not None
        assert '<span class="kn">import</span>' in text.html

    def test_text_truncated(self, make_target):
        limits = PreviewLimits(max_bytes=4)
        [text] = Text().preview(make_target("/a.txt", b"ab\ncd\nef\n"), limits)
        assert text.text == "ab\n"
        assert text.note.startswith("First 0 KB of 9 bytes")

    def test_markdown(self, make_target):
        [md] = Markdown().preview(make_target("/a.md", b"# Title\n"), self.limits)
        assert isinstance(md, MarkdownPreview)
        assert md.text == "# Title\n"

    def test_image(self, make_target):
        [media] = Image().preview(make_target("/a.png", b"\x89PNG"), self.limits)
        assert isinstance(media, MediaPreview)
        assert (media.mime, media.data) == ("image/png", b"\x89PNG")

    def test_install_hint_when_nothing_installed(self, make_target, monkeypatch):
        monkeypatch.setattr(Requirement, "is_installed", lambda self: False)
        [hint] = Csv().preview(make_target("/a.csv", b"a\n"), self.limits)
        assert isinstance(hint, InstallPreview)
        assert hint.options == [
            {"packages": "polars", "command": "%pip install -q polars"},
            {"packages": "pandas", "command": "%pip install -q pandas"},
        ]


class TestRecipes:
    def code(self, fmt, target) -> dict[str, str]:
        return {r.library: r.code for r in fmt.recipes(target)}

    def test_csv(self, make_target):
        code = self.code(Csv(), make_target("/a.tsv", b"x\ty\n"))
        assert (
            last_line(code["polars"])
            == "df = pl.read_csv('memory://a.tsv', separator='\\t')"
        )
        assert code["polars"].startswith("import polars as pl")
        assert (
            last_line(code["pandas"]) == "df = pd.read_csv('memory://a.tsv', sep='\\t')"
        )
        assert last_line(code["pyspark"]) == (
            "df = spark.read.csv('memory://a.tsv', header=True, inferSchema=True, sep='\\t')"
        )

    def test_parquet_directory_reads_its_own_files(self, make_target, memfs):
        memfs.pipe_file("/d/part-0.parquet", b"")
        code = self.code(Parquet(), make_target("/d"))
        assert (
            last_line(code["polars"]) == "df = pl.scan_parquet('memory://d/*.parquet')"
        )

    def test_delta(self, make_target, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        code = self.code(DeltaLake(), make_target("/t", url="s3://b/t"))
        assert last_line(code["polars"]) == "df = pl.scan_delta('s3://b/t')"
        assert (
            last_line(code["delta-spark"])
            == "df = spark.read.format(\"delta\").load('s3a://b/t')"
        )

    def test_json(self, make_target):
        code = self.code(Json(), make_target("/a.json", b"{}"))
        assert "data = json.load(f)" in code["fsspec"]
        assert last_line(code["polars"]) == "df = pl.read_json('memory://a.json')"

    def test_svg_has_no_recipe(self, make_target):
        assert Image().recipes(make_target("/a.svg", b"<svg/>")) == []

    def test_install_lines_only_for_missing_packages(self, make_target, monkeypatch):
        monkeypatch.setattr(Pillow, "is_installed", lambda self: False)
        [recipe] = Image().recipes(make_target("/a.png", b""))
        assert recipe.install == "%pip install -q pillow"  # fsspec is installed
        assert recipe.code.startswith("import PIL.Image\nimport fsspec")


class TestFormatOptionsInCode:
    def test_polars_and_pandas_options(self, make_target):
        fmt = Csv(
            polars_storage_options={"aws_region": "eu", "aws_secret_access_key": "s"},
            pandas_storage_options={"anon": True},
        )
        code = {r.library: r.code for r in fmt.recipes(make_target("/a.csv", b"x,y\n"))}
        assert last_line(code["polars"]) == (
            "df = pl.read_csv('memory://a.csv', storage_options={'aws_region': 'eu'})"
        )
        assert last_line(code["pandas"]) == (
            "df = pd.read_csv('memory://a.csv', storage_options={'anon': True})"
        )
        assert "storage_options" not in code["pyspark"]

    def test_fsspec_options(self, make_target):
        fmt = Text(fsspec_storage_options={"anon": True})
        [recipe] = fmt.recipes(make_target("/a.txt", b""))
        assert "fsspec.open('memory://a.txt', 'rt', anon=True)" in recipe.code

    def test_delta_options(self, make_target, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        fmt = DeltaLake(
            polars_storage_options={"region": "eu"},
            polars_delta_use_pyarrow=True,
            polars_delta_table_options={"version": 1},
        )
        polars_recipe = fmt.recipes(make_target("/t", url="s3://b/t"))[0]
        assert last_line(polars_recipe.code) == (
            "df = pl.scan_delta('s3://b/t', storage_options={'region': 'eu'}, "
            "delta_table_options={'version': 1}, use_pyarrow=True)"
        )

    def test_other_options_ignored(self):
        Text(polars_delta_use_pyarrow=True)  # no error


@pytest.mark.parametrize(
    ("fmt", "write", "name"),
    [
        (Parquet(), lambda df, p: df.write_parquet(p), "a.parquet"),
        (Csv(), lambda df, p: df.write_csv(p), "a.csv"),
        (JsonLines(), lambda df, p: df.write_ndjson(p), "a.jsonl"),
    ],
)
def test_scan_local_file(tmp_path, fmt, write, name):
    path = tmp_path / name
    write(pl.DataFrame({"a": [1, 2]}), path)
    assert fmt.scan(str(path), False).collect()["a"].to_list() == [1, 2]


def test_scan_delta_table(tmp_path):
    pl.DataFrame({"a": [1, 2]}).write_delta(tmp_path / "t")
    assert DeltaLake().scan(str(tmp_path / "t"), True).collect().height == 2


def test_scan_parquet_directory_skips_hidden_files(tmp_path):
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "part-0.parquet")
    pl.DataFrame({"a": [2]}).write_parquet(tmp_path / "part-1.parquet")
    (tmp_path / "_SUCCESS").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    pl.DataFrame({"a": [3]}).write_parquet(tmp_path / "sub" / "part-0.parquet")
    df = Parquet().scan(str(tmp_path), True).collect()
    assert sorted(df["a"].to_list()) == [1, 2]
