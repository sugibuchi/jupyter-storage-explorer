"""dask-support's supports: their views, the reads of the data browser, the
code and the options.

The fakes follow what Dask 2026.8 was measured to do through a filesystem
counting the bytes read (see the supports' module docstring)."""

from __future__ import annotations

import inspect
import io
import threading
from dataclasses import fields
from importlib.metadata import entry_points

import fsspec
import narwhals as nw
import pytest
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.memory import MemoryFileSystem
from jupyter_storage_explorer_dask_support import (
    CsvByDask,
    CsvByDaskOptions,
    DaskEngine,
    DaskOptions,
    JsonLinesByDask,
    JsonLinesByDaskOptions,
    ParquetByDask,
    ParquetByDaskOptions,
)

from jupyter_storage_explorer._query.data_query import fetch_rows
from jupyter_storage_explorer.filesystems.locations import S3Location
from jupyter_storage_explorer.formats import (
    Csv,
    JsonLines,
    Parquet,
    QueryView,
    ViewLimits,
    ViewWithConfirmation,
    local_file_cache,
)
from jupyter_storage_explorer.testing import item_of, local_item

dd = pytest.importorskip("dask.dataframe")
pd = pytest.importorskip("pandas")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

ROWS = 1000
FRAME = {"id": list(range(ROWS)), "x": [(i * 37) % 101 for i in range(ROWS)]}


def parquet_bytes(data=FRAME, row_group_size=100) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.table(data), buffer, row_group_size=row_group_size)
    return buffer.getvalue()


def csv_bytes(sep=",") -> bytes:
    return pd.DataFrame(FRAME).to_csv(index=False, sep=sep).encode()


def jsonl_bytes() -> bytes:
    return pd.DataFrame(FRAME).to_json(orient="records", lines=True).encode()


def rows(view, offset=0, length=ROWS + 1):
    """The rows the data browser reads, as a pandas DataFrame."""
    return fetch_rows(nw.from_native(view.data), offset, length).to_native()


# Bytes read through CountingFileSystem, which Dask reads as any fsspec
# filesystem. It is a module-level class: Dask names its graphs by pickling
# their filesystems, and a class it cannot import is pickled by value, which
# Dask refuses as not deterministic.
READ = {"bytes": 0}


class _CountedFile(io.BytesIO):
    def read(self, *args):
        data = super().read(*args)
        READ["bytes"] += len(data)
        return data


class CountingFileSystem(MemoryFileSystem):
    """fsspec's memory filesystem, counting the bytes read from its files."""

    protocol = "countingmem"

    @classmethod
    def _strip_protocol(cls, path):
        return super()._strip_protocol(path.removeprefix("countingmem://"))

    def _open(self, path, mode="rb", **kwargs):
        if "r" not in mode:
            return super()._open(path, mode, **kwargs)
        f = _CountedFile(self.store[self._strip_protocol(path)].getvalue())
        f.size = len(f.getvalue())
        return f

    def cat_file(self, path, start=None, end=None, **kwargs):
        with self._open(path) as f:
            size = f.size
            start = 0 if start is None else start if start >= 0 else size + start
            end = size if end is None else end if end >= 0 else size + end
            f.seek(start)
            return f.read(end - start)


fsspec.register_implementation("countingmem", CountingFileSystem, clobber=True)


@pytest.fixture
def counting(memfs):
    """The counting filesystem (sharing memfs's store), its count reset."""
    READ["bytes"] = 0
    return fsspec.filesystem("countingmem")


# --- The engine ---


def test_the_engine():
    assert DaskEngine.key == "dask"
    assert DaskEngine.label == "Dask"
    assert DaskEngine.is_installed()
    assert {p.package for p in DaskEngine.requirements} == {"dask", "pandas", "pyarrow"}


def test_supports_view_and_code_everywhere(make_item):
    item = make_item("/a.csv", csv_bytes())
    for task in ("view", "recipe"):
        assert CsvByDask().supports(Csv(), item, CsvByDaskOptions(), task)


# --- Parquet ---


def test_parquet_file_partitions_are_its_row_groups(make_item):
    item = make_item("/a.parquet", parquet_bytes())
    view = ParquetByDask().view(Parquet(), item, ParquetByDaskOptions(), ViewLimits())
    assert isinstance(view, QueryView)
    assert view.fetch is None  # the core reads Dask's partitions
    assert view.data.npartitions == ROWS // 100
    assert rows(view)["id"].tolist() == FRAME["id"]


def test_parquet_options_win(make_item):
    item = make_item("/a.parquet", parquet_bytes())
    options = ParquetByDaskOptions(split_row_groups=False, columns=["x"])
    view = ParquetByDask().view(Parquet(), item, options, ViewLimits())
    assert view.data.npartitions == 1
    assert list(view.data.columns) == ["x"]


def test_parquet_first_page_reads_the_first_row_groups(counting):
    n = 200_000
    big = {"id": list(range(n)), "x": [i * 0.5 for i in range(n)]}
    counting.pipe_file("/big.parquet", parquet_bytes(big, row_group_size=20_000))
    size = counting.size("/big.parquet")
    item = item_of(counting, "/big.parquet")
    view = ParquetByDask().view(Parquet(), item, ParquetByDaskOptions(), ViewLimits())
    READ["bytes"] = 0
    assert len(rows(view, 0, 101)) == 101
    # The first of 10 row groups, its footer read again, and no other.
    assert READ["bytes"] < size / 4


def test_parquet_hive_folder_of_files_without_extension(memfs, make_item):
    for year in (2024, 2025):
        memfs.pipe_file(f"/t/year={year}/000000_0", parquet_bytes())
    memfs.pipe_file("/t/_SUCCESS", b"")
    item = make_item("/t")
    fmt = Parquet()
    assert fmt.matches(item)
    view = ParquetByDask().view(fmt, item, ParquetByDaskOptions(), ViewLimits())
    df = rows(view, 0, 3 * ROWS)
    assert len(df) == 2 * ROWS
    assert sorted(df["year"].astype(int).unique()) == [2024, 2025]
    code = ParquetByDask().recipe(fmt, item, ParquetByDaskOptions())
    assert "parquet_file_extension=None" in code["Load as DataFrame"]


def test_parquet_through_a_dir_filesystem(memfs):
    memfs.pipe_file("/lake/t/part-0.parquet", parquet_bytes())
    memfs.pipe_file("/lake/t/part-1.parquet", parquet_bytes())
    fs = DirFileSystem("/lake", fs=memfs)
    item = item_of(fs, "t")
    fmt = Parquet()
    assert fmt.matches(item)
    view = ParquetByDask().view(fmt, item, ParquetByDaskOptions(), ViewLimits())
    assert view.data.npartitions == 2
    assert len(rows(view, 0, 3 * ROWS)) == 2 * ROWS


# --- The data browser's reads ---


def test_sorted_pages_are_read_in_one_pass(make_item):
    item = make_item("/a.parquet", parquet_bytes())
    view = ParquetByDask().view(Parquet(), item, ParquetByDaskOptions(), ViewLimits())
    lf = nw.from_native(view.data)
    query = lf.sort("x", "id", descending=[True, False]).select("id", "x")
    expected = pd.DataFrame(FRAME).sort_values(["x", "id"], ascending=[False, True])
    page = fetch_rows(query, 250, 20)
    assert page.to_native()["id"].tolist() == expected["id"].tolist()[250:270]


def test_the_data_is_read_in_another_thread(make_item):
    item = make_item("/a.csv", csv_bytes())
    view = CsvByDask().view(Csv(), item, CsvByDaskOptions(), ViewLimits())
    out = {}
    thread = threading.Thread(target=lambda: out.update(df=rows(view, 0, 10)))
    thread.start()
    thread.join()
    assert out["df"]["id"].tolist() == list(range(10))


# --- CSV and JSON Lines ---


def test_csv_in_blocks_with_its_separator(make_item):
    item = make_item("/a.csv", csv_bytes(sep=";"))
    limits = ViewLimits(max_whole_file_bytes=2000)
    view = CsvByDask().view(Csv(), item, CsvByDaskOptions(), limits)
    assert view.data.npartitions > 1
    df = rows(view)
    assert list(df.columns) == ["id", "x"]
    assert df["id"].tolist() == FRAME["id"]


def test_csv_options_win(make_item):
    item = make_item("/a.csv", csv_bytes())
    options = CsvByDaskOptions(blocksize=None, dtype={"x": "float64"}, usecols=["x"])
    view = CsvByDask().view(Csv(), item, options, ViewLimits())
    assert view.data.npartitions == 1
    assert str(view.data.dtypes["x"]) == "float64"


def test_csv_local_file(tmp_path):
    path = tmp_path / "a.tsv"
    path.write_bytes(csv_bytes(sep="\t"))
    view = CsvByDask().view(Csv(), local_item(path), CsvByDaskOptions(), ViewLimits())
    assert rows(view)["x"].tolist() == FRAME["x"]


def test_json_lines_in_blocks(make_item):
    item = make_item("/a.jsonl", jsonl_bytes())
    limits = ViewLimits(max_whole_file_bytes=4000)
    view = JsonLinesByDask().view(JsonLines(), item, JsonLinesByDaskOptions(), limits)
    assert view.data.npartitions > 1
    assert rows(view)["id"].tolist() == FRAME["id"]


def test_a_filesystem_fsspec_cannot_rebuild_is_copied_first(memfs):
    # skip_instance_cache: fsspec makes another instance from its options.
    fs = MemoryFileSystem(skip_instance_cache=True)
    assert fsspec.filesystem("memory", **fs.storage_options) is not fs
    fs.pipe_file("/copied.csv", csv_bytes())
    item = item_of(fs, "/copied.csv")
    cache = local_file_cache()
    small = CsvByDask().view(Csv(), item, CsvByDaskOptions(), ViewLimits())
    assert isinstance(small, QueryView)
    assert rows(small)["id"].tolist() == FRAME["id"]
    small.close()
    cache.release(item.location)  # what a later view would have reused
    fs.pipe_file("/large.csv", csv_bytes())
    large_item = item_of(fs, "/large.csv")
    limits = ViewLimits(max_whole_file_bytes=100)
    prompt = CsvByDask().view(Csv(), large_item, CsvByDaskOptions(), limits)
    assert isinstance(prompt, ViewWithConfirmation)
    view = prompt.answer()
    assert cache.status(large_item) == "cached"
    assert len(rows(view)) == ROWS
    view.close()


# --- Code ---


def run(code: str):
    namespace: dict = {}
    exec(code, namespace)
    return namespace["df"].compute()


def test_parquet_code_reads_the_file(tmp_path):
    path = tmp_path / "a.parquet"
    path.write_bytes(parquet_bytes())
    code = ParquetByDask().recipe(Parquet(), local_item(path), ParquetByDaskOptions())
    assert f"dd.read_parquet({path.as_posix()!r})" in code["Load as DataFrame"]
    assert run(code["Load as DataFrame"])["id"].tolist() == FRAME["id"]


def test_csv_code_has_the_separator(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(csv_bytes(sep="|"))
    options = CsvByDaskOptions(assume_missing=True)
    [code] = CsvByDask().recipe(Csv(), local_item(path), options).values()
    assert "sep='|'" in code and "assume_missing=True" in code
    assert run(code)["x"].tolist() == FRAME["x"]


def test_json_lines_code(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(jsonl_bytes())
    item = local_item(path)
    [code] = (
        JsonLinesByDask().recipe(JsonLines(), item, JsonLinesByDaskOptions()).values()
    )
    assert "lines=True" in code
    assert run(code)["id"].tolist() == FRAME["id"]


def test_remote_code_by_url_without_secrets(make_item):
    location = S3Location(bucket="lake", key="a.csv")
    item = make_item("/a.csv", csv_bytes(), location=location)
    options = CsvByDaskOptions(storage_options={"anon": False, "secret": "s3cr3t"})
    [code] = CsvByDask().recipe(Csv(), item, options).values()
    assert "dd.read_csv('s3://lake/a.csv', storage_options={'anon': False})" in code
    assert "s3cr3t" not in code


# --- Options ---


@pytest.mark.parametrize(
    ("model", "readers"),
    [
        (ParquetByDaskOptions, ["read_parquet"]),
        (CsvByDaskOptions, ["read_csv"]),
        (JsonLinesByDaskOptions, ["read_json"]),
    ],
)
def test_options_are_the_readers_arguments(model, readers):
    """Each option is an argument of Dask's reader, one its docstring lists
    under ``**kwargs``, or one of pandas' reader it passes its keyword
    arguments on to."""
    names = set()
    for reader in readers:
        dask_reader = getattr(dd, reader)
        names |= set(inspect.signature(dask_reader).parameters)
        names |= {
            n
            for n in ("dataset", "read", "open_file_options")
            if f"\n{n}" in dask_reader.__doc__
        }
        if reader != "read_parquet":
            names |= set(inspect.signature(getattr(pd, reader)).parameters)
    own = {f.name for f in fields(DaskOptions)}
    assert {f.name for f in fields(model)} - own <= names


def test_parquet_keyword_options_are_taken(make_item):
    """The options read_parquet takes through ``**kwargs``, with real values."""
    item = make_item("/a.parquet", parquet_bytes())
    options = ParquetByDaskOptions(
        dataset={"partitioning": None},
        read={},
        open_file_options={"precache_options": {"method": "parquet"}},
    )
    view = ParquetByDask().view(Parquet(), item, options, ViewLimits())
    assert len(rows(view)) == ROWS


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="dask-support"
    )
    plugin = entry_point.load()()
    assert plugin.key == "dask-support"
    assert plugin.description == "Dask support for Storage Explorer"
    assert set(plugin.format_supports) == {ParquetByDask, CsvByDask, JsonLinesByDask}
