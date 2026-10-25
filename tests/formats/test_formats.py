"""Each default format: detection, and the core's views and code (the
engines' are tested in their plugins, plugins/<name>-support/tests)."""

from __future__ import annotations

import io

import polars as pl
import pytest
from all_actions import all_actions

from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Image,
    Json,
    Markdown,
    MarkdownView,
    MediaView,
    Parquet,
    PythonPackage,
    Text,
    TextView,
    TreeView,
    ViewLimits,
)

CHAIN = ActionChain(all_actions())


def parquet_bytes(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def library(recipe) -> str:
    """The library a recipe loads with: its first package."""
    return recipe.requirements[0].package


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


def view(fmt, item, limits=LIMITS):
    """``fmt``'s view of ``item`` by the built-in views (no engine)."""
    return CHAIN.view(fmt, item, limits, None)


class TestViews:
    def test_json_tree(self, make_item):
        tree = view(Json(), make_item("/a.json", b'{"a": [1, 2]}'))
        assert isinstance(tree, TreeView)
        assert tree.value == {"a": [1, 2]}

    def test_invalid_json_shown_as_text(self, make_item):
        text = view(Json(), make_item("/a.json", b"{oops"))
        assert isinstance(text, TextView)
        assert text.note.startswith("Invalid JSON")

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
        assert text.note == "First 4 B of 9 B"

    def test_markdown(self, make_item):
        md = view(Markdown(), make_item("/a.md", b"# Title\n"))
        assert isinstance(md, MarkdownView)
        assert md.text == "# Title\n"

    def test_image(self, make_item):
        media = view(Image(), make_item("/a.png", b"\x89PNG"))
        assert isinstance(media, MediaView)
        assert (media.mime, media.data) == ("image/png", b"\x89PNG")

    def test_nothing_installed(self, make_item, monkeypatch):
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        assert CHAIN.of(Csv(), make_item("/a.csv", b"")) == []

    def test_image_needs_no_package(self, make_item, monkeypatch):
        # The browser shows images itself: Pillow is for the load code only.
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        assert isinstance(view(Image(), make_item("/a.png", b"\x89PNG")), MediaView)


class TestRecipes:
    def test_json(self, make_item):
        recipes = CHAIN.recipes(Json(), make_item("/a.json", b"{}"))
        code = {f"{library(r)}: {r.title}": r.code for r in recipes}
        assert "data = json.load(f)" in code["fsspec: Load the JSON value"]

    def test_svg_has_no_recipe(self, make_item):
        assert CHAIN.recipes(Image(), make_item("/a.svg", b"<svg/>")) == []

    def test_runs_in_a_new_notebook(self, make_item):
        # Its imports first, whatever the notebook has imported.
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

    def test_python_options(self, make_item):
        chain = ActionChain(
            all_actions(), {"python": {"*": {"storage_options": {"anon": True}}}}
        )
        [recipe] = chain.recipes(Text(), make_item("/a.txt", b""))
        assert recipe.title == "Read the text"
        assert "fsspec.open('memory:///a.txt', 'rt', anon=True)" in recipe.code
