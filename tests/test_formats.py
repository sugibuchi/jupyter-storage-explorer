"""Each default format: detection, and its default supports' views and code."""

from __future__ import annotations

import io
import json

import pandas as pd
import polars as pl
import pytest
from items import local_item

from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer.filesystems import S3Location
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Excel,
    Image,
    Json,
    JsonLines,
    Markdown,
    MarkdownView,
    MediaView,
    Parquet,
    PythonPackage,
    QueryView,
    Text,
    TextView,
    TreeView,
    ViewLimits,
    default_supports,
)
from jupyter_storage_explorer.formats.packages import Pillow
from jupyter_storage_explorer.formats.supports import (
    CsvByPandas,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPandas,
    JsonLinesByPandas,
    PandasOptions,
    ParquetByPandas,
)
from jupyter_storage_explorer.formats.supports.pyspark import spark_url

CHAIN = SupportChain(default_supports())


def parquet_bytes(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def library(recipe) -> str:
    """The library a recipe loads with: its first package."""
    return recipe.requirements[0].package


def last_line(code: str) -> str:
    return code.strip().splitlines()[-1]


class TestParquetDetection:
    def test_spark_output(self, make_item, memfs):
        for i in range(3):
            memfs.pipe_file(
                f"/out/part-0000{i}-2e8a686a-d04f-4489-ad50-a834723e6591-c000.snappy.parquet",
                b"",
            )
        memfs.pipe_file("/out/_SUCCESS", b"")
        memfs.pipe_file("/out/.part-00000.crc", b"")
        assert Parquet().matches(make_item("/out"))

    def test_differently_named_tables_are_not_one_dataset(self, make_item, memfs):
        memfs.pipe_file("/d/orders.parquet", b"")
        memfs.pipe_file("/d/customers.parquet", b"")
        assert not Parquet().matches(make_item("/d"))

    def test_folder_with_other_files(self, make_item, memfs):
        memfs.pipe_file("/d/part-0.parquet", b"")
        memfs.pipe_file("/d/readme.md", b"")
        assert not Parquet().matches(make_item("/d"))

    def test_hive_files_checked_by_magic_bytes(self, make_item, memfs):
        memfs.pipe_file("/hive/000000_0", parquet_bytes(pl.DataFrame({"a": [1]})))
        memfs.pipe_file("/hive/000001_0", b"")
        assert Parquet().matches(make_item("/hive"))
        memfs.pipe_file("/orc/000000_0", b"ORC...")
        assert not Parquet().matches(make_item("/orc"))

    def test_hudi_table_is_not_a_dataset(self, make_item, memfs):
        # Its files hold versions of rows: read as Parquet, stale ones show.
        memfs.pipe_file("/h/part-0.parquet", b"")
        memfs.pipe_file("/h/.hoodie/hoodie.properties", b"")
        assert not Parquet().matches(make_item("/h"))


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

    def test_two_columns_with_two_more_listings(self, make_item, memfs, listings):
        self.table(memfs)
        item = make_item("/t")
        listings.clear()
        fmt = Parquet()
        assert fmt.matches(item)
        assert listings == ["/t/year=2025", "/t/year=2025/month=1"]
        assert fmt.layout(item).glob(item.location.url) == (
            "memory:///t/year=*/month=*/*.parquet"
        )

    def test_a_partition_of_it_too(self, make_item, memfs):
        self.table(memfs)
        assert Parquet().matches(make_item("/t/year=2025"))
        assert Parquet().matches(make_item("/t/year=2025/month=1"))

    def test_other_folders_cost_nothing(self, make_item, memfs, listings):
        memfs.pipe_file("/d/year=2025/part-0.parquet", b"")
        memfs.pipe_file("/d/notes/a.txt", b"")
        item = make_item("/d")
        listings.clear()
        assert not Parquet().matches(item)
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
    def test_not_partitioned_parquet(self, make_item, memfs, paths):
        for path in paths:
            memfs.pipe_file(f"/d/{path}", b"")
        assert not Parquet().matches(make_item("/d"))

    def test_an_empty_partition_passed_over(self, make_item, memfs):
        memfs.pipe_file("/t/year=2024/_SUCCESS", b"")
        memfs.pipe_file("/t/year=2025/part-0.parquet", b"")
        assert Parquet().matches(make_item("/t"))
        memfs.pipe_file("/u/year=2023/_SUCCESS", b"")
        memfs.pipe_file("/u/year=2024/_SUCCESS", b"")
        memfs.pipe_file("/u/year=2025/part-0.parquet", b"")
        assert not Parquet().matches(make_item("/u"))  # two empty: given up

    def test_at_most_five_columns(self, make_item, memfs):
        memfs.pipe_file("/t/a=1/b=1/c=1/d=1/e=1/part-0.parquet", b"")
        assert Parquet().matches(make_item("/t"))
        memfs.pipe_file("/u/a=1/b=1/c=1/d=1/e=1/f=1/part-0.parquet", b"")
        assert not Parquet().matches(make_item("/u"))

    def test_hive_files_checked_by_magic_bytes(self, make_item, memfs):
        data = parquet_bytes(pl.DataFrame({"a": [1]}))
        memfs.pipe_file("/t/dt=2026-10-01/000000_0", data)
        fmt = Parquet()
        item = make_item("/t")
        assert fmt.matches(item)
        assert fmt.layout(item).files == "*"
        memfs.pipe_file("/orc/dt=2026-10-01/000000_0", b"ORC...")
        assert not Parquet().matches(make_item("/orc"))


def test_delta_detection(make_item, memfs):
    memfs.pipe_file("/t/_delta_log/0.json", b"{}")
    assert DeltaLake().matches(make_item("/t"))
    memfs.pipe_file("/u/part-0.parquet", b"")
    assert not DeltaLake().matches(make_item("/u"))


LIMITS = ViewLimits(max_display_rows=2)
# pandas reads at most max_memory_rows rows.
PANDAS_LIMITS = ViewLimits(max_memory_rows=2)


def view(fmt, item, limits=LIMITS):
    """``fmt``'s view of ``item``, by the support the explorer would pick:
    its first engine's (Polars), else the built-in views'."""
    return CHAIN.view(fmt, item, limits, CHAIN.viewers(fmt)[0])


def data(fmt, item):
    """The data of ``fmt``'s view of ``item``: a QueryView's."""
    query = view(fmt, item)
    assert isinstance(query, QueryView)
    return query.data


class TestViews:
    def test_csv_in_the_data_browser(self, tmp_path):
        # polars reads by URL: a local file.
        path = tmp_path / "a.csv"
        path.write_text("x;y\n1;2\n3;4\n")
        df = data(Csv(), local_item(path)).collect()
        assert df.columns == ["x", "y"]  # the separator detected
        assert df.rows() == [(1, 2), (3, 4)]

    def test_csv_with_pandas(self, make_item):
        # pandas reads through the item's fsspec filesystem, eagerly: the
        # first max_memory_rows rows, in the data browser.
        item = make_item("/a.csv", b"x;y\n1;2\n3;4\n5;6\n")
        query = CsvByPandas().view(Csv(), item, PandasOptions(), PANDAS_LIMITS)
        assert isinstance(query, QueryView)
        assert list(query.data.columns) == ["x", "y"]  # the separator detected
        assert query.data.values.tolist() == [[1, 2], [3, 4]]
        assert query.more

    def test_json_tree(self, make_item):
        tree = view(Json(), make_item("/a.json", b'{"a": [1, 2]}'))
        assert isinstance(tree, TreeView)
        assert tree.value == {"a": [1, 2]}

    def test_invalid_json_shown_as_text(self, make_item):
        text = view(Json(), make_item("/a.json", b"{oops"))
        assert isinstance(text, TextView)
        assert text.note.startswith("Invalid JSON")

    def test_json_lines_with_pandas(self, make_item):
        lines = b"".join(json.dumps({"i": i}).encode() + b"\n" for i in range(5))
        item = make_item("/a.jsonl", lines)
        query = JsonLinesByPandas().view(
            JsonLines(), item, PandasOptions(), PANDAS_LIMITS
        )
        assert query.data["i"].tolist() == [0, 1]
        assert query.more

    def test_parquet_file_with_pandas(self, make_item):
        # pyarrow reads through the item's fsspec filesystem, so memory:// works.
        item = make_item("/a.parquet", parquet_bytes(pl.DataFrame({"a": [1, 2, 3]})))
        query = ParquetByPandas().view(Parquet(), item, PandasOptions(), PANDAS_LIMITS)
        assert query.data["a"].tolist() == [1, 2]
        assert query.more
        whole = ParquetByPandas().view(Parquet(), item, PandasOptions(), LIMITS)
        assert (whole.data["a"].tolist(), whole.more) == ([1, 2, 3], False)

    def test_parquet_file_in_the_data_browser(self, tmp_path):
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1, 2, 3]}).write_parquet(path)
        assert data(Parquet(), local_item(path)).collect()["a"].to_list() == [1, 2, 3]

    def test_excel_in_the_data_browser(self, make_item):
        # polars reads the workbook through the explorer's filesystem.
        frame = data(Excel(), make_item("/a.xlsx", self.workbook()))
        # Read whole (a DataFrame), queried in memory; the first sheet.
        assert frame["a"].to_list() == [1, 2, 3]

    def test_excel_with_pandas(self, make_item):
        item = make_item("/a.xlsx", self.workbook())
        # The first sheet, as with polars.
        query = ExcelByPandas().view(Excel(), item, PandasOptions(), PANDAS_LIMITS)
        assert (query.data["a"].tolist(), query.more) == ([1, 2], True)

    def workbook(self) -> bytes:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1, 2, 3]}).to_excel(
                writer, sheet_name="one", index=False
            )
            pd.DataFrame({"b": [1]}).to_excel(writer, sheet_name="two", index=False)
        return buffer.getvalue()

    def test_text_highlighted(self, make_item):
        text = view(Text(), make_item("/a.py", b"import os\n"))
        assert text.language == "python"
        assert text.html is not None
        assert '<span class="kn">import</span>' in text.html

    def test_text_truncated(self, make_item):
        text = view(
            Text(), make_item("/a.txt", b"ab\ncd\nef\n"), ViewLimits(max_bytes=4)
        )
        assert text.text == "ab\n"
        assert text.note.startswith("First 0 KB of 9 bytes")

    def test_markdown(self, make_item):
        md = view(Markdown(), make_item("/a.md", b"# Title\n"))
        assert isinstance(md, MarkdownView)
        assert md.text == "# Title\n"

    def test_image(self, make_item):
        media = view(Image(), make_item("/a.png", b"\x89PNG"))
        assert isinstance(media, MediaView)
        assert (media.mime, media.data) == ("image/png", b"\x89PNG")

    def test_nothing_installed(self, monkeypatch):
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        assert CHAIN.of(Csv(), "view") == []

    def test_image_needs_no_package(self, make_item, monkeypatch):
        # The browser shows images itself: Pillow is for the load code only.
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        assert isinstance(view(Image(), make_item("/a.png", b"\x89PNG")), MediaView)


def code_of(recipes) -> dict[str, str]:
    """Recipes' code by "library: title"."""
    return {f"{library(r)}: {r.title}": r.code for r in recipes}


class TestRecipes:
    def code(self, fmt, item) -> dict[str, str]:
        return code_of(CHAIN.recipes(fmt, item))

    def test_csv(self, make_item):
        code = self.code(Csv(), make_item("/a.tsv", b"x\ty\n"))
        assert list(code) == [
            "polars: Load as DataFrame",
            "pandas: Load as DataFrame",
            "pyspark: Load as DataFrame",
        ]
        polars = code["polars: Load as DataFrame"]
        assert polars.startswith("import polars as pl")
        assert (
            last_line(polars) == "df = pl.read_csv('memory:///a.tsv', separator='\\t')"
        )
        assert last_line(code["pandas: Load as DataFrame"]) == (
            "df = pd.read_csv('memory:///a.tsv', sep='\\t')"
        )
        assert last_line(code["pyspark: Load as DataFrame"]) == (
            "df = spark.read.csv('memory:///a.tsv', header=True, inferSchema=True, sep='\\t')"
        )

    def test_lazy_and_eager_with_polars(self, make_item, memfs):
        memfs.pipe_file("/d/part-0.parquet", b"")
        code = self.code(Parquet(), make_item("/d"))
        assert last_line(code["polars: Load as LazyFrame"]) == (
            "df = pl.scan_parquet('memory:///d/*.parquet')"
        )
        assert last_line(code["polars: Load as DataFrame"]) == (
            "df = pl.read_parquet('memory:///d/*.parquet')"
        )
        lines = self.code(JsonLines(), make_item("/a.jsonl", b"{}\n"))
        assert last_line(lines["polars: Load as LazyFrame"]) == (
            "df = pl.scan_ndjson('memory:///a.jsonl')"
        )
        assert last_line(lines["polars: Load as DataFrame"]) == (
            "df = pl.read_ndjson('memory:///a.jsonl')"
        )

    def test_delta(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        code = self.code(
            DeltaLake(), make_item("/t", location=S3Location(bucket="b", key="t"))
        )
        assert last_line(code["polars: Load as LazyFrame"]) == (
            "df = pl.scan_delta('s3://b/t')"
        )
        assert last_line(code["polars: Load as DataFrame"]) == (
            "df = pl.read_delta('s3://b/t')"
        )
        # The session is obtained, not configured: Delta Lake's setup in
        # Spark is left to the user.
        assert code["pyspark: Load as DataFrame"] == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "# Needs Delta Lake in the Spark session (Databricks has it)\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.format(\"delta\").load('s3a://b/t')"
        )

    def test_json(self, make_item):
        code = self.code(Json(), make_item("/a.json", b"{}"))
        assert "data = json.load(f)" in code["fsspec: Load the JSON value"]
        assert last_line(code["polars: Load as DataFrame"]) == (
            "df = pl.read_json('memory:///a.json')"
        )

    def test_svg_has_no_recipe(self, make_item):
        assert CHAIN.recipes(Image(), make_item("/a.svg", b"<svg/>")) == []

    def test_runs_in_a_new_notebook(self, make_item, monkeypatch):
        # Its imports first, whatever the notebook has imported; missing
        # packages are not installed by the code.
        monkeypatch.setattr(Pillow, "is_installed", lambda self: False)
        [recipe] = CHAIN.recipes(Image(), make_item("/a.png", b""))
        assert recipe.title == "Open the image"
        assert recipe.code == (
            "import fsspec\n"
            "import PIL.Image\n"
            "\n"
            "with fsspec.open('memory:///a.png', 'rb') as f:\n"
            "    img = PIL.Image.open(f)\n"
            "    img.load()\n"
            "img"
        )

    def test_spark_session_created(self, make_item):
        code = self.code(Parquet(), make_item("/a.parquet", b""))
        assert code["pyspark: Load as DataFrame"] == (
            "from pyspark.sql import SparkSession\n"
            "\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "df = spark.read.parquet('memory:///a.parquet')"
        )


def test_spark_url(tmp_path):
    assert spark_url("s3://bucket/x") == "s3a://bucket/x"
    assert (
        spark_url("abfs://c@a.dfs.core.windows.net/x")
        == "abfss://c@a.dfs.core.windows.net/x"
    )
    assert spark_url("az://c/x") == "abfss://c/x"
    assert spark_url("gs://bucket/x") == "gs://bucket/x"
    # Local files: Spark reads their file:/// URLs.
    assert spark_url(local_item(tmp_path).location.url).startswith("file:///")


def options_chain(options):
    return SupportChain(default_supports(), options)


class TestFormatOptionsInCode:
    def test_polars_and_pandas_options(self, make_item):
        chain = options_chain(
            {
                "polars": {
                    "*": {
                        "storage_options": {
                            "aws_region": "eu",
                            "aws_secret_access_key": "s",
                        }
                    }
                },
                "pandas": {"*": {"storage_options": {"anon": True}}},
            }
        )
        code = code_of(chain.recipes(Csv(), make_item("/a.csv", b"x,y\n")))
        assert last_line(code["polars: Load as DataFrame"]) == (
            "df = pl.read_csv('memory:///a.csv', storage_options={'aws_region': 'eu'})"
        )
        assert last_line(code["pandas: Load as DataFrame"]) == (
            "df = pd.read_csv('memory:///a.csv', storage_options={'anon': True})"
        )
        assert "storage_options" not in code["pyspark: Load as DataFrame"]

    def test_python_options(self, make_item):
        chain = options_chain({"python": {"*": {"storage_options": {"anon": True}}}})
        [recipe] = chain.recipes(Text(), make_item("/a.txt", b""))
        assert recipe.title == "Read the text"
        assert "fsspec.open('memory:///a.txt', 'rt', anon=True)" in recipe.code

    def test_delta_options(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        options = DeltaLakeByPolarsOptions(
            storage_options={"region": "eu"},
            use_pyarrow=True,
            delta_table_options={"version": 1},
        )
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        code = DeltaLakeByPolars().recipe(DeltaLake(), item, options)
        options = (
            "'s3://b/t', storage_options={'region': 'eu'}, "
            "delta_table_options={'version': 1}, use_pyarrow=True)"
        )
        assert last_line(code["Load as LazyFrame"]) == f"df = pl.scan_delta({options}"
        assert last_line(code["Load as DataFrame"]) == f"df = pl.read_delta({options}"


@pytest.mark.parametrize(
    ("fmt", "write", "name"),
    [
        (Parquet(), lambda df, p: df.write_parquet(p), "a.parquet"),
        (Csv(), lambda df, p: df.write_csv(p), "a.csv"),
        (JsonLines(), lambda df, p: df.write_ndjson(p), "a.jsonl"),
    ],
)
def test_query_local_file(tmp_path, fmt, write, name):
    path = tmp_path / name
    write(pl.DataFrame({"a": [1, 2]}), path)
    assert data(fmt, local_item(path)).collect()["a"].to_list() == [1, 2]


def test_query_delta_table(tmp_path):
    pl.DataFrame({"a": [1, 2]}).write_delta(tmp_path / "t")
    assert data(DeltaLake(), local_item(tmp_path / "t")).collect().height == 2


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
        assert fmt.matches(local_item(tmp_path))
        df = data(fmt, local_item(tmp_path)).collect().sort("a")
        assert df.columns == ["a", "year", "month"]
        assert df.rows() == [
            (202501, 2025, 1),
            (202502, 2025, 2),
            (202601, 2026, 1),
            (202602, 2026, 2),
        ]

    def test_scan_of_a_folder_not_detected(self, tmp_path):
        # Its layout is found then, through the filesystem given.
        self.write(tmp_path)
        df = data(Parquet(), local_item(tmp_path)).collect()
        assert (df.columns, df.height) == (["a", "year", "month"], 4)

    def test_scan_hive_files(self, tmp_path):
        folder = tmp_path / "dt=2026-10-01"
        folder.mkdir()
        pl.DataFrame({"a": [1, 2]}).write_parquet(folder / "000000_0")
        (folder / "_SUCCESS").write_bytes(b"")
        fmt = Parquet()
        assert fmt.matches(local_item(tmp_path))
        df = data(fmt, local_item(tmp_path)).collect()
        assert df["a"].to_list() == [1, 2]
        assert df.columns == ["a", "dt"]

    def test_pandas_view_of_one_partition(self, make_item, memfs):
        for year in (2025, 2026):
            data = parquet_bytes(pl.DataFrame({"a": [year, year]}))
            memfs.pipe_file(f"/t/year={year}/part-0.parquet", data)
        fmt = Parquet()
        item = make_item("/t")
        assert fmt.matches(item)
        query = ParquetByPandas().view(fmt, item, PandasOptions(), LIMITS)
        # Every partition, its column from the folders' names.
        assert list(query.data.columns) == ["a", "year"]
        assert query.data["year"].astype(int).tolist() == [2025, 2025, 2026, 2026]

    def test_code(self, make_item, memfs):
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        code = code_of(CHAIN.recipes(Parquet(), make_item("/t")))
        assert last_line(code["polars: Load as LazyFrame"]) == (
            "df = pl.scan_parquet('memory:///t/year=*/month=*/*.parquet', "
            "hive_partitioning=True)"
        )
        assert last_line(code["polars: Load as DataFrame"]) == (
            "df = pl.read_parquet('memory:///t/year=*/month=*/*.parquet', "
            "hive_partitioning=True)"
        )
        # pandas (pyarrow) and Spark find partitions themselves.
        assert last_line(code["pandas: Load as DataFrame"]) == (
            "df = pd.read_parquet('memory:///t')"
        )
        assert last_line(code["pyspark: Load as DataFrame"]) == (
            "df = spark.read.parquet('memory:///t')"
        )

    def test_code_for_hive_files(self, make_item, memfs):
        frame = parquet_bytes(pl.DataFrame({"a": [1]}))
        memfs.pipe_file("/t/dt=2026-10-01/000000_0", frame)
        code = code_of(CHAIN.recipes(Parquet(), make_item("/t")))
        options = "'memory:///t/dt=*/*', hive_partitioning=True, hidden_file_prefix=['.', '_'])"
        assert last_line(code["polars: Load as LazyFrame"]) == (
            f"df = pl.scan_parquet({options}"
        )
        # read_parquet takes no hidden_file_prefix: scanned, then read.
        assert last_line(code["polars: Load as DataFrame"]) == (
            f"df = pl.scan_parquet({options}.collect()"
        )


def test_scan_parquet_directory_skips_hidden_files(tmp_path):
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "part-0.parquet")
    pl.DataFrame({"a": [2]}).write_parquet(tmp_path / "part-1.parquet")
    (tmp_path / "_SUCCESS").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    pl.DataFrame({"a": [3]}).write_parquet(tmp_path / "sub" / "part-0.parquet")
    df = data(Parquet(), local_item(tmp_path)).collect()
    assert sorted(df["a"].to_list()) == [1, 2]
