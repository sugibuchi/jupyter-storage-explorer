"""polars-support: its supports' views (polars reads by URL: local files) and
code, its options, and its entry point."""

from __future__ import annotations

import io
from importlib.metadata import entry_points

import openpyxl
import polars as pl
import pytest
from jupyter_storage_explorer_polars_support import (
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    JsonByPolars,
    JsonLinesByPolars,
    ParquetByPolars,
    PolarsOptions,
    PolarsSupport,
)

from jupyter_storage_explorer.filesystems import S3Location
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Excel,
    Json,
    JsonLines,
    Parquet,
    QueryView,
    ViewLimits,
)
from jupyter_storage_explorer.testing import local_item

LIMITS = ViewLimits(max_display_rows=2)


def parquet_bytes(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def last_line(code: str) -> str:
    return code.strip().splitlines()[-1]


def data(support, fmt, item, options=None):
    """The data of the support's view of ``item``: a QueryView's."""
    view = support.view(fmt, item, options or support.options_model(), LIMITS)
    assert isinstance(view, QueryView)
    return view.data


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="polars-support"
    )
    plugin = entry_point.load()()
    assert isinstance(plugin, PolarsSupport)
    assert plugin.description == "Polars support for Storage Explorer"
    assert CsvByPolars in plugin.format_supports


class TestViews:
    def test_csv_with_its_separator(self, tmp_path):
        path = tmp_path / "a.csv"
        path.write_text("x;y\n1;2\n3;4\n")
        df = data(CsvByPolars(), Csv(), local_item(path)).collect()
        assert df.columns == ["x", "y"]  # the separator detected
        assert df.rows() == [(1, 2), (3, 4)]

    @pytest.mark.parametrize(
        ("support", "fmt", "write", "name"),
        [
            (
                ParquetByPolars(),
                Parquet(),
                lambda df, p: df.write_parquet(p),
                "a.parquet",
            ),
            (CsvByPolars(), Csv(), lambda df, p: df.write_csv(p), "a.csv"),
            (
                JsonLinesByPolars(),
                JsonLines(),
                lambda df, p: df.write_ndjson(p),
                "a.jsonl",
            ),
        ],
    )
    def test_local_file(self, tmp_path, support, fmt, write, name):
        path = tmp_path / name
        write(pl.DataFrame({"a": [1, 2]}), path)
        assert data(support, fmt, local_item(path)).collect()["a"].to_list() == [1, 2]

    def test_delta_table(self, tmp_path):
        pl.DataFrame({"a": [1, 2]}).write_delta(tmp_path / "t")
        frame = data(DeltaLakeByPolars(), DeltaLake(), local_item(tmp_path / "t"))
        assert frame.collect().height == 2

    def test_excel(self, make_item):
        # polars reads the workbook through the explorer's filesystem: read
        # whole (a DataFrame), queried in memory; the first sheet.
        workbook = openpyxl.Workbook()
        workbook.active.title = "one"
        for row in (["a"], [1], [2], [3]):
            workbook.active.append(row)
        workbook.create_sheet("two").append(["b"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        item = make_item("/a.xlsx", buffer.getvalue())
        frame = data(ExcelByPolars(), Excel(), item, ExcelByPolarsOptions())
        assert frame["a"].to_list() == [1, 2, 3]

    def test_parquet_folder_skips_hidden_files(self, tmp_path):
        pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "part-0.parquet")
        pl.DataFrame({"a": [2]}).write_parquet(tmp_path / "part-1.parquet")
        (tmp_path / "_SUCCESS").write_bytes(b"")
        (tmp_path / "sub").mkdir()
        pl.DataFrame({"a": [3]}).write_parquet(tmp_path / "sub" / "part-0.parquet")
        df = data(ParquetByPolars(), Parquet(), local_item(tmp_path)).collect()
        assert sorted(df["a"].to_list()) == [1, 2]


class TestPartitionedParquet:
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
        df = data(ParquetByPolars(), fmt, local_item(tmp_path)).collect().sort("a")
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
        df = data(ParquetByPolars(), Parquet(), local_item(tmp_path)).collect()
        assert (df.columns, df.height) == (["a", "year", "month"], 4)

    def test_scan_hive_files(self, tmp_path):
        folder = tmp_path / "dt=2026-10-01"
        folder.mkdir()
        pl.DataFrame({"a": [1, 2]}).write_parquet(folder / "000000_0")
        (folder / "_SUCCESS").write_bytes(b"")
        fmt = Parquet()
        assert fmt.matches(local_item(tmp_path))
        df = data(ParquetByPolars(), fmt, local_item(tmp_path)).collect()
        assert df["a"].to_list() == [1, 2]
        assert df.columns == ["a", "dt"]

    def test_code(self, make_item, memfs):
        memfs.pipe_file("/t/year=2025/month=1/part-0.parquet", b"")
        code = ParquetByPolars().recipe(Parquet(), make_item("/t"), PolarsOptions())
        assert last_line(code["Load as LazyFrame"]) == (
            "df = pl.scan_parquet('memory:///t/year=*/month=*/*.parquet', "
            "hive_partitioning=True)"
        )
        assert last_line(code["Load as DataFrame"]) == (
            "df = pl.read_parquet('memory:///t/year=*/month=*/*.parquet', "
            "hive_partitioning=True)"
        )

    def test_code_for_hive_files(self, make_item, memfs):
        frame = parquet_bytes(pl.DataFrame({"a": [1]}))
        memfs.pipe_file("/t/dt=2026-10-01/000000_0", frame)
        code = ParquetByPolars().recipe(Parquet(), make_item("/t"), PolarsOptions())
        options = "'memory:///t/dt=*/*', hive_partitioning=True, hidden_file_prefix=['.', '_'])"
        assert last_line(code["Load as LazyFrame"]) == f"df = pl.scan_parquet({options}"
        # read_parquet takes no hidden_file_prefix: scanned, then read.
        assert last_line(code["Load as DataFrame"]) == (
            f"df = pl.scan_parquet({options}.collect()"
        )


class TestRecipes:
    def test_csv(self, make_item):
        code = CsvByPolars().recipe(
            Csv(), make_item("/a.tsv", b"x\ty\n"), PolarsOptions()
        )
        [frame] = code.values()
        assert frame.startswith("import polars as pl")
        assert (
            last_line(frame) == "df = pl.read_csv('memory:///a.tsv', separator='\\t')"
        )

    def test_lazy_and_eager(self, make_item, memfs):
        memfs.pipe_file("/d/part-0.parquet", b"")
        code = ParquetByPolars().recipe(Parquet(), make_item("/d"), PolarsOptions())
        assert last_line(code["Load as LazyFrame"]) == (
            "df = pl.scan_parquet('memory:///d/*.parquet')"
        )
        assert last_line(code["Load as DataFrame"]) == (
            "df = pl.read_parquet('memory:///d/*.parquet')"
        )
        lines = JsonLinesByPolars().recipe(
            JsonLines(), make_item("/a.jsonl", b"{}\n"), PolarsOptions()
        )
        assert last_line(lines["Load as LazyFrame"]) == (
            "df = pl.scan_ndjson('memory:///a.jsonl')"
        )
        assert last_line(lines["Load as DataFrame"]) == (
            "df = pl.read_ndjson('memory:///a.jsonl')"
        )

    def test_delta(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        code = DeltaLakeByPolars().recipe(DeltaLake(), item, DeltaLakeByPolarsOptions())
        assert last_line(code["Load as LazyFrame"]) == "df = pl.scan_delta('s3://b/t')"
        assert last_line(code["Load as DataFrame"]) == "df = pl.read_delta('s3://b/t')"

    def test_json(self, make_item):
        code = JsonByPolars().recipe(
            Json(), make_item("/a.json", b"{}"), PolarsOptions()
        )
        assert last_line(code["Load as DataFrame"]) == (
            "df = pl.read_json('memory:///a.json')"
        )


class TestOptions:
    def test_storage_options_without_secrets(self, make_item):
        options = PolarsOptions(
            storage_options={"aws_region": "eu", "aws_secret_access_key": "s"}
        )
        [code] = (
            CsvByPolars().recipe(Csv(), make_item("/a.csv", b"x,y\n"), options).values()
        )
        assert last_line(code) == (
            "df = pl.read_csv('memory:///a.csv', storage_options={'aws_region': 'eu'})"
        )

    def test_delta_options(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/0.json", b"{}")
        options = DeltaLakeByPolarsOptions(
            storage_options={"region": "eu"},
            use_pyarrow=True,
            delta_table_options={"version": 1},
        )
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        code = DeltaLakeByPolars().recipe(DeltaLake(), item, options)
        expected = (
            "'s3://b/t', storage_options={'region': 'eu'}, "
            "delta_table_options={'version': 1}, use_pyarrow=True)"
        )
        assert last_line(code["Load as LazyFrame"]) == f"df = pl.scan_delta({expected}"
        assert last_line(code["Load as DataFrame"]) == f"df = pl.read_delta({expected}"

    def test_option_names(self):
        assert PolarsOptions.option_names() == {
            "storage_options",
            "credential_provider",
        }
        assert DeltaLakeByPolarsOptions.option_names() >= {
            "use_pyarrow",
            "storage_options",
        }
