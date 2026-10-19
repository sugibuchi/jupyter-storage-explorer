"""Each default format: detection, previews and the code snippets of its recipes."""

from __future__ import annotations

import io
import json

import fsspec
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

    def test_hudi_table_is_not_a_dataset(self, make_target, memfs):
        # Its files hold versions of rows: read as Parquet, stale ones show.
        memfs.pipe_file("/h/part-0.parquet", b"")
        memfs.pipe_file("/h/.hoodie/hoodie.properties", b"")
        assert not Parquet().matches(make_target("/h"))


class TestPartitionedParquetDetection:
    """Hive-style partition folders ("year=2026/month=9/…"), checked down one
    branch: one more listing per partition column."""

    @pytest.fixture
    def listings(self, memfs, monkeypatch):
        """The folders listed by detection, besides the listing it is given."""
        listed = []
        ls = memfs.ls

        def counting(path, *args, **kwargs):
            listed.append(path)
            return ls(path, *args, **kwargs)

        monkeypatch.setattr(memfs, "ls", counting)
        return listed

    def table(self, memfs, root="/t", name="part-0.parquet"):
        for year in (2025, 2026):
            for month in (1, 2):
                memfs.pipe_file(f"{root}/year={year}/month={month}/{name}", b"")
                memfs.pipe_file(f"{root}/year={year}/month={month}/_SUCCESS", b"")
        memfs.pipe_file(f"{root}/_SUCCESS", b"")

    def test_two_columns_with_two_more_listings(self, make_target, memfs, listings):
        self.table(memfs)
        target = make_target("/t")
        listings.clear()
        fmt = Parquet()
        assert fmt.matches(target)
        assert listings == ["/t/year=2025", "/t/year=2025/month=1"]
        assert fmt._layout("memory://t").glob("memory://t") == (
            "memory://t/year=*/month=*/*.parquet"
        )

    def test_a_partition_of_it_too(self, make_target, memfs):
        self.table(memfs)
        assert Parquet().matches(make_target("/t/year=2025"))
        assert Parquet().matches(make_target("/t/year=2025/month=1"))

    def test_other_folders_cost_nothing(self, make_target, memfs, listings):
        memfs.pipe_file("/d/year=2025/part-0.parquet", b"")
        memfs.pipe_file("/d/notes/a.txt", b"")
        target = make_target("/d")
        listings.clear()
        assert not Parquet().matches(target)
        assert listings == []

    @pytest.mark.parametrize(
        "paths",
        [
            # Folders of two columns side by side.
            ["year=2025/part-0.parquet", "month=1/part-0.parquet"],
            # A data file beside the partitions.
            ["year=2025/part-0.parquet", "part-0.parquet"],
            # CSV partitions.
            ["year=2025/part-0.csv", "year=2026/part-0.csv"],
            # The same column twice.
            ["year=2025/year=1/part-0.parquet"],
            # Partitions holding other folders.
            ["year=2025/data/part-0.parquet"],
        ],
    )
    def test_not_partitioned_parquet(self, make_target, memfs, paths):
        for path in paths:
            memfs.pipe_file(f"/d/{path}", b"")
        assert not Parquet().matches(make_target("/d"))

    def test_an_empty_partition_passed_over(self, make_target, memfs):
        memfs.pipe_file("/t/year=2024/_SUCCESS", b"")
        memfs.pipe_file("/t/year=2025/part-0.parquet", b"")
        assert Parquet().matches(make_target("/t"))
        memfs.pipe_file("/u/year=2023/_SUCCESS", b"")
        memfs.pipe_file("/u/year=2024/_SUCCESS", b"")
        memfs.pipe_file("/u/year=2025/part-0.parquet", b"")
        assert not Parquet().matches(make_target("/u"))  # two empty: given up

    def test_at_most_five_columns(self, make_target, memfs):
        memfs.pipe_file("/t/a=1/b=1/c=1/d=1/e=1/part-0.parquet", b"")
        assert Parquet().matches(make_target("/t"))
        memfs.pipe_file("/u/a=1/b=1/c=1/d=1/e=1/f=1/part-0.parquet", b"")
        assert not Parquet().matches(make_target("/u"))

    def test_hive_files_checked_by_magic_bytes(self, make_target, memfs):
        data = parquet_bytes(pl.DataFrame({"a": [1]}))
        memfs.pipe_file("/t/dt=2026-10-01/000000_0", data)
        fmt = Parquet()
        assert fmt.matches(make_target("/t"))
        assert fmt._layout("memory://t").files == "*"
        memfs.pipe_file("/orc/dt=2026-10-01/000000_0", b"ORC...")
        assert not Parquet().matches(make_target("/orc"))


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
        assert hint.options == [["polars"], ["pandas"]]


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
        # The session is obtained, not configured: Delta Lake's setup in
        # Spark is left to the user.
        assert code["delta-spark"] == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "# Needs Delta Lake in the Spark session (Databricks has it)\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.format(\"delta\").load('s3a://b/t')"
        )

    def test_json(self, make_target):
        code = self.code(Json(), make_target("/a.json", b"{}"))
        assert "data = json.load(f)" in code["fsspec"]
        assert last_line(code["polars"]) == "df = pl.read_json('memory://a.json')"

    def test_svg_has_no_recipe(self, make_target):
        assert Image().recipes(make_target("/a.svg", b"<svg/>")) == []

    def test_runs_in_a_new_notebook(self, make_target, monkeypatch):
        # Its imports first, whatever the notebook has imported; missing
        # packages are not installed by the code.
        monkeypatch.setattr(Pillow, "is_installed", lambda self: False)
        [recipe] = Image().recipes(make_target("/a.png", b""))
        assert recipe.code == (
            "import fsspec\n"
            "import PIL.Image\n"
            "\n"
            "with fsspec.open('memory://a.png', 'rb') as f:\n"
            "    img = PIL.Image.open(f)\n"
            "    img.load()\n"
            "img"
        )

    def test_spark_session_created(self, make_target):
        code = self.code(Parquet(), make_target("/a.parquet", b""))
        assert code["pyspark"] == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.parquet('memory://a.parquet')"
        )


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


def local_target(path) -> Target:
    """A local directory's Target, as the explorer gives it to ``matches``."""
    fs = fsspec.filesystem("file")
    path = path.as_posix()
    return Target(
        fs=fs, path=path, url=path, info={}, children=fs.ls(path, detail=True)
    )


class TestPartitionedParquetReading:
    def write(self, root):
        for year in (2025, 2026):
            for month in (1, 2):
                folder = root / f"year={year}" / f"month={month}"
                folder.mkdir(parents=True)
                pl.DataFrame({"a": [year * 100 + month]}).write_parquet(
                    folder / "part-0.parquet"
                )
                (folder / "_SUCCESS").write_bytes(b"")
        # Left by a writer: not part of the table.
        (root / "_temporary" / "0").mkdir(parents=True)
        pl.DataFrame({"a": [-1]}).write_parquet(root / "_temporary" / "0" / "x.parquet")

    def test_scan_with_partition_columns(self, tmp_path):
        self.write(tmp_path)
        fmt = Parquet()
        assert fmt.matches(local_target(tmp_path))
        df = fmt.scan(tmp_path.as_posix(), True).collect().sort("a")
        assert df.columns == ["a", "year", "month"]
        assert df.rows() == [
            (202501, 2025, 1),
            (202502, 2025, 2),
            (202601, 2026, 1),
            (202602, 2026, 2),
        ]

    def test_scan_of_a_url_not_detected(self, tmp_path):
        # E.g. rewritten by a subclass's scan: its layout is found then.
        self.write(tmp_path)
        df = Parquet().scan(tmp_path.as_posix(), True).collect()
        assert (df.columns, df.height) == (["a", "year", "month"], 4)

    def test_scan_hive_files(self, tmp_path):
        folder = tmp_path / "dt=2026-10-01"
        folder.mkdir()
        pl.DataFrame({"a": [1, 2]}).write_parquet(folder / "000000_0")
        (folder / "_SUCCESS").write_bytes(b"")
        fmt = Parquet()
        assert fmt.matches(local_target(tmp_path))
        df = fmt.scan(tmp_path.as_posix(), True).collect()
        assert df["a"].to_list() == [1, 2]
        assert df.columns == ["a", "dt"]

    def test_pandas_preview_of_one_partition(self, make_target, memfs):
        for year in (2025, 2026):
            data = parquet_bytes(pl.DataFrame({"a": [year, year]}))
            memfs.pipe_file(f"/t/year={year}/part-0.parquet", data)
        fmt = Parquet()
        target = make_target("/t")
        assert fmt.matches(target)
        [table] = fmt.preview_with_pandas(target, PreviewLimits(max_rows=5))
        assert table.columns == ["a", "year"]
        assert table.rows == [[2025, 2025], [2025, 2025]]

    def test_code(self, make_target, memfs):
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        fmt = Parquet()
        code = {r.library: r.code for r in fmt.recipes(make_target("/t"))}
        assert last_line(code["polars"]) == (
            "df = pl.scan_parquet('memory://t/year=*/month=*/*.parquet', "
            "hive_partitioning=True)"
        )
        # pandas (pyarrow) and Spark find partitions themselves.
        assert last_line(code["pandas"]) == "df = pd.read_parquet('memory://t')"
        assert last_line(code["pyspark"]) == "df = spark.read.parquet('memory://t')"

    def test_code_for_hive_files(self, make_target, memfs):
        data = parquet_bytes(pl.DataFrame({"a": [1]}))
        memfs.pipe_file("/t/dt=2026-10-01/000000_0", data)
        code = {r.library: r.code for r in Parquet().recipes(make_target("/t"))}
        assert last_line(code["polars"]) == (
            "df = pl.scan_parquet('memory://t/dt=*/*', hive_partitioning=True, "
            "hidden_file_prefix=['.', '_'])"
        )


def test_scan_parquet_directory_skips_hidden_files(tmp_path):
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "part-0.parquet")
    pl.DataFrame({"a": [2]}).write_parquet(tmp_path / "part-1.parquet")
    (tmp_path / "_SUCCESS").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    pl.DataFrame({"a": [3]}).write_parquet(tmp_path / "sub" / "part-0.parquet")
    df = Parquet().scan(str(tmp_path), True).collect()
    assert sorted(df["a"].to_list()) == [1, 2]
