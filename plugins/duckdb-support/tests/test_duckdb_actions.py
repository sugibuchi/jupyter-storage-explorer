"""duckdb-support: its actions' views, by URL (local files) and through the
explorer's filesystem (fsspec's memory filesystem), their code, its database
format, its options, and its entry point."""

from __future__ import annotations

import dataclasses
import threading
from importlib.metadata import entry_points

import duckdb
import narwhals as nw
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import write_deltalake
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.local import LocalFileSystem
from fsspec.spec import AbstractFileSystem
from jupyter_storage_explorer_duckdb_support import (
    DUCKDB_ACTIONS,
    CsvByDuckDBOptions,
    DeltaLakeByDuckDBOptions,
    DuckDBDatabase,
    DuckDBOptions,
    DuckDBSupport,
    JsonLinesByDuckDBOptions,
    ParquetByDuckDBOptions,
    csv_as_relation,
    csv_view,
    database_code,
    database_view,
    delta_as_relation,
    delta_view,
    json_lines_as_relation,
    json_lines_view,
    parquet_as_relation,
    parquet_view,
)
from jupyter_storage_explorer_duckdb_support import actions as duckdb_actions
from jupyter_storage_explorer_duckdb_support.actions import _read_by_duckdb

from jupyter_storage_explorer.actions import LocalFileCache
from jupyter_storage_explorer.filesystems.locations import (
    AbfsLocation,
    S3Location,
    SftpLocation,
)
from jupyter_storage_explorer.formats import Csv, DeltaLake, JsonLines, Parquet
from jupyter_storage_explorer.formats.base import detect
from jupyter_storage_explorer.testing import item_of, local_item
from jupyter_storage_explorer.views import (
    QueryView,
    TableSetView,
    TextView,
    ViewLimits,
    ViewWithChoice,
    ViewWithConfirmation,
)

LIMITS = ViewLimits(max_display_rows=2)
SQLITE_BYTES = b"SQLite format 3\0" + b"\0" * 100


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch) -> LocalFileCache:
    """The actions' local copies, in a cache of each test's own."""
    cache = LocalFileCache(tmp_path / "copies")
    monkeypatch.setattr(duckdb_actions, "local_file_cache", lambda: cache)
    return cache


def parquet_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def rows(data) -> list[dict]:
    """The rows of a view's data, as the data browser reads them: through
    narwhals."""
    return nw.from_native(data).collect().to_native().to_pylist()


def query_view(action, fmt, item, options=None, limits=LIMITS) -> QueryView:
    view = action(fmt, item, options or action.options_model(), limits)
    assert isinstance(view, QueryView)
    return view


def database(path, sql: str) -> None:
    con = duckdb.connect(str(path))
    con.sql(sql)
    con.close()


def test_plugin_registered():
    [entry_point] = entry_points(
        group="jupyter_storage_explorer.plugins", name="duckdb-support"
    )
    plugin = entry_point.load()()
    assert isinstance(plugin, DuckDBSupport)
    assert plugin.description == "DuckDB support for Storage Explorer"
    assert plugin.actions == DUCKDB_ACTIONS
    assert parquet_view in plugin.actions
    assert database_view in plugin.actions


def test_one_options_class_per_format():
    # A format's view and code take the same options.
    by_format: dict[type, set[type]] = {}
    for action in DUCKDB_ACTIONS:
        by_format.setdefault(action.format, set()).add(action.options_model)
    assert all(len(models) == 1 for models in by_format.values())


def test_names():
    assert [(a.format, a.label) for a in DUCKDB_ACTIONS] == [
        (DeltaLake, "View as Delta Lake table (DuckDB)"),
        (DeltaLake, "Load as relation"),
        (Parquet, "View as Parquet (DuckDB)"),
        (Parquet, "Load as relation"),
        (Csv, "View as CSV (DuckDB)"),
        (Csv, "Load as relation"),
        (JsonLines, "View as JSON Lines (DuckDB)"),
        (JsonLines, "Load as relation"),
        (DuckDBDatabase, "View as DuckDB database (DuckDB)"),
        (DuckDBDatabase, "Open the database"),
    ]


class TestDatabaseFormat:
    def test_detected_by_its_signature(self, tmp_path):
        database(tmp_path / "a.db", "create table t as select 1 as a")
        (tmp_path / "b.db").write_bytes(SQLITE_BYTES)
        fmt = DuckDBDatabase()
        assert detect(local_item(tmp_path / "a.db"), formats=[fmt]) is fmt
        assert detect(local_item(tmp_path / "b.db"), formats=[fmt]) is None

    def test_listings_read_nothing(self, tmp_path):
        database(tmp_path / "a.duckdb", "create table t as select 1 as a")
        item = local_item(tmp_path / "a.duckdb")
        assert detect(item, formats=[DuckDBDatabase()], sniff=False) is None


class TestParquet:
    def test_local_file(self, tmp_path):
        pq.write_table(pa.table({"a": [1, 2]}), tmp_path / "a.parquet")
        view = query_view(parquet_view, Parquet(), local_item(tmp_path / "a.parquet"))
        assert rows(view.data) == [{"a": 1}, {"a": 2}]
        view.close()

    def test_folder_skips_hidden_files(self, tmp_path):
        pq.write_table(pa.table({"a": [1]}), tmp_path / "part-0.parquet")
        pq.write_table(pa.table({"a": [2]}), tmp_path / "part-1.parquet")
        (tmp_path / "_SUCCESS").write_bytes(b"")
        data = query_view(parquet_view, Parquet(), local_item(tmp_path)).data
        assert sorted(r["a"] for r in rows(data)) == [1, 2]

    def write_partitions(self, fs, root: str) -> None:
        for year in (2025, 2026):
            for month in (1, 2):
                folder = f"{root}/year={year}/month={month}"
                fs.pipe_file(
                    f"{folder}/part-0.parquet",
                    parquet_bytes(pa.table({"a": [year * 100 + month]})),
                )
                fs.pipe_file(f"{folder}/_SUCCESS", b"")
        # Left by a writer: not part of the table.
        fs.pipe_file(
            f"{root}/_temporary/0/x.parquet", parquet_bytes(pa.table({"a": [-1]}))
        )

    def test_partitioned_folder(self, tmp_path):
        self.write_partitions(LocalFileSystem(auto_mkdir=True), tmp_path.as_posix())
        fmt = Parquet()
        item = local_item(tmp_path)
        assert fmt.matches(item)
        data = query_view(parquet_view, fmt, item).data
        assert sorted(rows(data), key=lambda r: r["a"]) == [
            {"a": 202501, "month": 1, "year": 2025},
            {"a": 202502, "month": 2, "year": 2025},
            {"a": 202601, "month": 1, "year": 2026},
            {"a": 202602, "month": 2, "year": 2026},
        ]

    def test_file_through_the_explorers_filesystem(self, make_item):
        # The memory filesystem: no storage DuckDB reads itself.
        item = make_item("/d/a.parquet", parquet_bytes(pa.table({"a": [1, 2]})))
        assert not _read_by_duckdb(Parquet(), item, ParquetByDuckDBOptions())
        view = query_view(parquet_view, Parquet(), item)
        assert rows(view.data) == [{"a": 1}, {"a": 2}]
        view.close()

    def test_partitioned_folder_through_the_explorers_filesystem(
        self, memfs, make_item
    ):
        self.write_partitions(memfs, "/d/t")
        fmt = Parquet()
        item = make_item("/d/t")
        assert fmt.matches(item)
        data = query_view(parquet_view, fmt, item).data
        assert sorted(r["a"] for r in rows(data)) == [202501, 202502, 202601, 202602]

    def test_hive_files_through_the_explorers_filesystem(self, memfs, make_item):
        # Files named without an extension: "[!_.]*" leaves out "_SUCCESS".
        memfs.pipe_file("/h/dt=1/000000_0", parquet_bytes(pa.table({"a": [1, 2]})))
        memfs.pipe_file("/h/dt=1/_SUCCESS", b"")
        fmt = Parquet()
        item = make_item("/h")
        assert fmt.matches(item)
        assert fmt.layout(item).files == "*"
        data = query_view(parquet_view, fmt, item).data
        assert rows(data) == [{"a": 1, "dt": 1}, {"a": 2, "dt": 1}]

    def test_relative_paths_of_a_dir_filesystem(self, memfs):
        # A DirFileSystem's paths are relative: the item's path, not its URL.
        memfs.pipe_file("/root/d/a.parquet", parquet_bytes(pa.table({"a": [1]})))
        fs = DirFileSystem("/root", fs=memfs)
        item = item_of(fs, "d/a.parquet")
        assert rows(query_view(parquet_view, Parquet(), item).data) == [{"a": 1}]

    def test_read_in_another_thread(self, make_item):
        # The data browser reads the data in its lane's thread, not the view's.
        item = make_item("/d/a.parquet", parquet_bytes(pa.table({"a": [1, 2, 3]})))
        data = query_view(parquet_view, Parquet(), item).data
        found = {}
        thread = threading.Thread(
            target=lambda: found.update(
                n=nw.from_native(data).select(nw.len()).collect().item()
            )
        )
        thread.start()
        thread.join()
        assert found == {"n": 3}

    def test_closing_closes_the_connection(self, tmp_path):
        pq.write_table(pa.table({"a": [1]}), tmp_path / "a.parquet")
        view = query_view(parquet_view, Parquet(), local_item(tmp_path / "a.parquet"))
        view.close()
        with pytest.raises(duckdb.ConnectionException):
            view.data.fetchall()

    def test_options_are_read_parquets_arguments(self, tmp_path):
        pq.write_table(pa.table({"a": [1]}), tmp_path / "a.parquet")
        options = ParquetByDuckDBOptions(filename=True, config={"threads": 1})
        data = query_view(
            parquet_view, Parquet(), local_item(tmp_path / "a.parquet"), options
        ).data
        assert set(rows(data)[0]) == {"a", "filename"}

    def test_url_schemes_read_by_url(self, make_item):
        item = make_item(
            "/b/a.parquet", b"", location=S3Location(bucket="b", key="a.parquet")
        )
        assert not _read_by_duckdb(Parquet(), item, DuckDBOptions())
        assert _read_by_duckdb(Parquet(), item, DuckDBOptions(url_schemes=["S3"]))


class TestTheExplorersFilesystem:
    """Parquet off the storages DuckDB reads itself: the explorer's
    filesystem registered as it is, read by its own URL of the item."""

    def test_a_dir_filesystem(self, memfs):
        memfs.pipe_file("/root/data/a.parquet", parquet_bytes(pa.table({"n": [1, 2]})))
        fs = DirFileSystem("/root", fs=memfs)
        item = item_of(fs, "data/a.parquet")
        data = query_view(parquet_view, Parquet(), item).data
        assert rows(data) == [{"n": 1}, {"n": 2}]

    def test_refused_without_modified(self, make_item):
        # DuckDB calls modified() for each file, and fails without it.
        class NoModified(AbstractFileSystem):
            protocol = "nomod"

        item = dataclasses.replace(make_item("/a.parquet", b""), fs=NoModified())
        options = ParquetByDuckDBOptions()
        assert not parquet_view.does(Parquet(), item, options)
        assert parquet_as_relation.does(Parquet(), item, options)


class TestText:
    def test_local_csv_with_its_separator(self, tmp_path):
        (tmp_path / "a.csv").write_text("x;y\n1;a\n2;b\n")
        data = query_view(csv_view, Csv(), local_item(tmp_path / "a.csv")).data
        assert rows(data) == [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]

    def test_local_json_lines(self, tmp_path):
        (tmp_path / "a.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
        data = query_view(
            json_lines_view, JsonLines(), local_item(tmp_path / "a.jsonl")
        ).data
        assert rows(data) == [{"a": 1}, {"a": 2}]

    def test_options_are_read_csvs_arguments(self, tmp_path):
        (tmp_path / "a.csv").write_text("1,2\n3,4\n")
        options = CsvByDuckDBOptions(header=False, names=["p", "q"])
        data = query_view(csv_view, Csv(), local_item(tmp_path / "a.csv"), options).data
        assert rows(data) == [{"p": 1, "q": 2}, {"p": 3, "q": 4}]

    def test_small_remote_file_copied(self, make_item, cache):
        item = make_item("/d/a.csv", b"x,y\n1,2\n")
        view = query_view(csv_view, Csv(), item)
        assert cache.status(item) == "cached"
        assert rows(view.data) == [{"x": 1, "y": 2}]
        view.close()
        assert cache.status(item) == "cached"  # kept a while, for the next view

    def test_large_remote_file_asks_first(self, make_item, cache):
        lines = b"".join(b"%d,%d\n" % (i, i * 2) for i in range(1000))
        item = make_item("/d/a.csv", b"a,b\n" + lines)
        limits = ViewLimits(max_whole_file_bytes=100)
        prompt = csv_view(Csv(), item, CsvByDuckDBOptions(), limits)
        assert isinstance(prompt, ViewWithChoice)
        assert list(prompt.choices) == ["Its first 100 B", "The whole file (8.1 KB)"]
        assert cache.status(item) == "not_cached"
        first = prompt.answer("Its first 100 B")
        assert first.more
        assert [r["a"] for r in rows(first.data)] == list(range(len(rows(first.data))))
        assert len(rows(first.data)) < 1000
        whole = prompt.answer("The whole file (8.1 KB)")
        assert not whole.more and len(rows(whole.data)) == 1000
        assert cache.status(item) == "cached"
        # Copied: viewed again without asking.
        view = csv_view(Csv(), item, CsvByDuckDBOptions(), limits)
        assert isinstance(view, QueryView)

    def test_remote_json_lines_first_bytes(self, make_item):
        lines = b"".join(b'{"a": %d}\n' % i for i in range(100))
        item = make_item("/d/a.jsonl", lines)
        prompt = json_lines_view(
            JsonLines(),
            item,
            JsonLinesByDuckDBOptions(),
            ViewLimits(max_whole_file_bytes=50),
        )
        view = prompt.answer("Its first 50 B")
        assert view.more
        assert rows(view.data) == [{"a": 0}, {"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}]


@pytest.fixture
def delta_extension():
    """DuckDB's delta extension, downloaded once by DuckDB; skipped where it
    cannot be."""
    try:
        con = duckdb.connect()
        con.install_extension("delta")
        con.load_extension("delta")
    except duckdb.Error as error:
        pytest.skip(f"no delta extension: {error}")


class TestDeltaLake:
    def write(self, path) -> None:
        write_deltalake(str(path), pa.table({"a": [1]}))
        write_deltalake(str(path), pa.table({"a": [2]}), mode="append")

    def test_local_table(self, tmp_path, delta_extension):
        self.write(tmp_path / "t")
        item = local_item(tmp_path / "t")
        data = query_view(delta_view, DeltaLake(), item).data
        assert sorted(r["a"] for r in rows(data)) == [1, 2]
        options = DeltaLakeByDuckDBOptions(version=0)
        data = query_view(delta_view, DeltaLake(), item, options).data
        assert rows(data) == [{"a": 1}]

    def test_by_url_only(self, make_item):
        options = DeltaLakeByDuckDBOptions()
        on_memory = make_item("/t", b"")
        assert not delta_view.does(DeltaLake(), on_memory, options)
        assert not delta_as_relation.does(DeltaLake(), on_memory, options)
        on_s3 = make_item("/t", b"", location=S3Location(bucket="b", key="t"))
        assert not delta_view.does(DeltaLake(), on_s3, options)
        assert delta_as_relation.does(DeltaLake(), on_s3, options)
        s3 = DeltaLakeByDuckDBOptions(url_schemes=["s3"])
        assert delta_view.does(DeltaLake(), on_s3, s3)

    def test_code(self, make_item):
        item = make_item("/t", b"", location=S3Location(bucket="b", key="it's"))
        options = DeltaLakeByDuckDBOptions(version=3)
        code = delta_as_relation(DeltaLake(), item, options)
        assert "select * from delta_scan('s3://b/it''s', version := 3)" in code


class TestDatabase:
    SQL = (
        "create schema sales; create table sales.orders as select range as id from range(3);"
        " create table main.t as select 1 as a; create view main.v as select a * 2 as b from t"
    )

    def test_tables_and_views_by_schema(self, tmp_path):
        database(tmp_path / "a.duckdb", self.SQL)
        item = local_item(tmp_path / "a.duckdb")
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), LIMITS)
        assert isinstance(view, TableSetView)
        assert [(n.label, [c.label for c in n.children]) for n in view.nodes] == [
            ("main", ["t", "v"]),
            ("sales", ["orders"]),
        ]
        assert {n.icon for n in view.nodes} == {"database"}
        assert {c.icon for n in view.nodes for c in n.children} == {"table"}
        assert rows(view.loader('"sales"."orders"')) == [
            {"id": 0},
            {"id": 1},
            {"id": 2},
        ]
        assert rows(view.loader('"main"."v"')) == [{"b": 2}]
        view.close()

    def test_one_schema_without_it(self, tmp_path):
        database(tmp_path / "a.duckdb", 'create table "my ""t""" as select 1 as a')
        item = local_item(tmp_path / "a.duckdb")
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), LIMITS)
        [leaf] = view.nodes
        assert leaf.label == 'my "t"'
        assert rows(view.loader(leaf.id)) == [{"a": 1}]
        view.close()

    def test_no_tables(self, tmp_path):
        database(tmp_path / "a.duckdb", "select 1")
        item = local_item(tmp_path / "a.duckdb")
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), LIMITS)
        assert isinstance(view, TextView)

    def test_remote_database_copied(self, tmp_path, make_item, cache):
        database(tmp_path / "a.duckdb", self.SQL)
        item = make_item("/dbs/a.duckdb", (tmp_path / "a.duckdb").read_bytes())
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), ViewLimits())
        assert isinstance(view, TableSetView)
        assert cache.status(item) == "cached"
        assert rows(view.loader('"main"."t"')) == [{"a": 1}]
        view.close()

    def test_large_remote_database_asks_first(self, tmp_path, make_item, cache):
        database(tmp_path / "a.duckdb", self.SQL)
        item = make_item("/dbs/a.duckdb", (tmp_path / "a.duckdb").read_bytes())
        limits = ViewLimits(max_whole_file_bytes=1000)
        prompt = database_view(DuckDBDatabase(), item, DuckDBOptions(), limits)
        assert isinstance(prompt, ViewWithConfirmation)
        assert cache.status(item) == "not_cached"
        view = prompt.answer()
        assert isinstance(view, TableSetView)
        view.close()
        # Copied: viewed again without asking.
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), limits)
        assert isinstance(view, TableSetView)
        view.close()

    def test_copy_released_on_close(self, tmp_path, make_item, cache, monkeypatch):
        monkeypatch.setattr(duckdb_actions, "_COPY_KEPT", 0)
        database(tmp_path / "a.duckdb", self.SQL)
        item = make_item("/dbs/a.duckdb", (tmp_path / "a.duckdb").read_bytes())
        view = database_view(DuckDBDatabase(), item, DuckDBOptions(), ViewLimits())
        view.close()
        assert cache.status(item) == "not_cached"

    def test_code(self, tmp_path, make_item):
        database(tmp_path / "a.duckdb", self.SQL)
        local = local_item(tmp_path / "a.duckdb")
        options = DuckDBOptions(config={"threads": 2, "s3_secret_access_key": "x"})
        source = database_code(DuckDBDatabase(), local, options)
        path = (tmp_path / "a.duckdb").as_posix()
        assert (
            f"duckdb.connect({path!r}, read_only=True, config={{'threads': 2}})"
            in source
        )
        namespace = {}
        exec(source, namespace)
        namespace["con"].close()
        location = SftpLocation(host="h", path="/dbs/a.duckdb")
        remote = make_item("/dbs/a.duckdb", b"", location=location)
        options = DuckDBOptions(
            fsspec_storage_options={"username": "u", "password": "p"}
        )
        source = database_code(DuckDBDatabase(), remote, options)
        assert (
            "fsspec.open_local('simplecache::sftp://h:22/dbs/a.duckdb', sftp={'username': 'u'})"
            in source
        )


class TestCode:
    def test_local_parquet_runs(self, tmp_path):
        pq.write_table(pa.table({"a": [1, 2]}), tmp_path / "a.parquet")
        item = local_item(tmp_path / "a.parquet")
        source = parquet_as_relation(Parquet(), item, ParquetByDuckDBOptions())
        assert f"rel = con.read_parquet({item.url_or_local_path!r})" in source
        namespace = {}
        exec(source, namespace)
        assert namespace["rel"].fetchall() == [(1,), (2,)]

    def test_partitioned_parquet(self, make_item, memfs):
        memfs.pipe_file("/t/year=1/a.parquet", parquet_bytes(pa.table({"a": [1]})))
        item = make_item("/t", location=S3Location(bucket="b", key="t"))
        source = parquet_as_relation(Parquet(), item, ParquetByDuckDBOptions())
        assert (
            "con.read_parquet('s3://b/t/year=*/*.parquet', hive_partitioning=True)"
            in source
        )

    def test_storages_duckdb_does_not_read_through_fsspec(self, make_item):
        # The memory filesystem's code: fsspec's, registered with DuckDB.
        item = make_item("/d/a.parquet", parquet_bytes(pa.table({"a": [1]})))
        source = parquet_as_relation(Parquet(), item, ParquetByDuckDBOptions())
        assert "fsspec.url_to_fs('memory:///d/a.parquet')" in source
        namespace = {}
        exec(source, namespace)
        assert namespace["rel"].fetchall() == [(1,)]

    def test_azure_as_duckdb_reads_it(self, make_item):
        location = AbfsLocation(account_name="acc", container_name="c", path="a.csv")
        item = make_item("/c/a.csv", b"a\n1\n", location=location)
        source = csv_as_relation(Csv(), item, CsvByDuckDBOptions())
        assert "con.read_csv('abfss://c@acc.dfs.core.windows.net/a.csv')" in source

    def test_options_without_secrets(self, make_item):
        item = make_item(
            "/b/a.jsonl", b"", location=S3Location(bucket="b", key="a.jsonl")
        )
        options = JsonLinesByDuckDBOptions(
            config={"threads": 2, "s3_secret_access_key": "x"}, ignore_errors=True
        )
        source = json_lines_as_relation(JsonLines(), item, options)
        assert "con = duckdb.connect(config={'threads': 2})" in source
        assert (
            "con.read_json('s3://b/a.jsonl', format='newline_delimited', ignore_errors=True)"
            in source
        )
        assert "secret" not in source

    def test_fsspec_options_without_secrets(self, make_item):
        location = SftpLocation(host="h", path="/d/a.csv")
        item = make_item("/d/a.csv", b"a\n1\n", location=location)
        options = CsvByDuckDBOptions(
            fsspec_storage_options={"username": "u", "password": "p"}, header=True
        )
        source = csv_as_relation(Csv(), item, options)
        assert "fs, _ = fsspec.url_to_fs('sftp://h:22/d/a.csv', username='u')" in source
        assert "con.read_csv('sftp://h:22/d/a.csv', header=True)" in source
