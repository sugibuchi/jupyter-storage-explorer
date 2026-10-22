"""StorageExplorer's previews, data browser, view tabs and right-click menu."""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import threading

import pytest
from explorers import entries, make, path_of
from format_samples import DUCKDB_BYTES, SQLITE_BYTES, DuckDB, SQLite
from in_a_kernel import until
from jupyter_storage_explorer_pandas_support import CsvByPandas
from jupyter_storage_explorer_polars_support import CsvByPolars

from jupyter_storage_explorer._explorer import previews
from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer._view_tab import ViewTab
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    FormatSupport,
    PythonPackage,
    TableView,
    Text,
    TextView,
    ViewLimits,
)


class TestPreview:
    def test_text(self, local):
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        assert local._preview["format"] == "text"
        [section] = local._preview["sections"]
        assert (section["kind"], section["text"]) == ("text", "hello\n")

    def test_query_view_opens_the_data_browser(self, local):
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path})
        assert local._preview["format"] == "parquet"
        assert [c["name"] for c in local._preview["query"]["columns"]] == ["a"]
        reply = local.request(
            {"type": "query_rows", "rid": 7, "path": path, "offset": 0, "window": 2}
        )
        assert reply["type"] == "reply"
        assert reply["rid"] == 7
        assert (reply["rows"], reply["more"]) == ([[1], [2]], True)

    def test_viewed_once_and_again_on_reload(self, local, monkeypatch):
        calls = []
        view = SupportChain.view

        def counting(self, *args, **kwargs):
            calls.append(args[0])
            return view(self, *args, **kwargs)

        monkeypatch.setattr(SupportChain, "view", counting)
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path})
        assert len(calls) == 1  # the data browser gets the data viewed
        local.request({"type": "query_reload", "rid": 1, "path": path})
        assert len(calls) == 2

    def test_reload_views_the_item_as_it_is_now(self, tmp_path, monkeypatch):
        # A dataset folder gaining a file: the reload's context has its new
        # listing and info, not those of when it was opened.
        pl = pytest.importorskip("polars")
        (tmp_path / "ds").mkdir()
        pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "ds" / "part-0.parquet")
        contexts = []
        view = SupportChain.view

        def recording(self, fmt, ctx, *args, **kwargs):
            contexts.append(ctx)
            return view(self, fmt, ctx, *args, **kwargs)

        monkeypatch.setattr(SupportChain, "view", recording)
        explorer = make(str(tmp_path))
        path = path_of(explorer, "ds")
        explorer.message({"type": "preview", "path": path})
        pl.DataFrame({"a": [2]}).write_parquet(tmp_path / "ds" / "part-1.parquet")
        reply = explorer.request({"type": "query_reload", "rid": 1, "path": path})
        assert "error" not in reply
        first, again = (sorted(c.child_names) for c in contexts)
        assert (first, again) == (
            ["part-0.parquet"],
            ["part-0.parquet", "part-1.parquet"],
        )
        rows = explorer.request(
            {"type": "query_rows", "rid": 2, "path": path, "offset": 0, "window": 5}
        )
        assert sorted(rows["rows"]) == [[1], [2]]

    @pytest.mark.parametrize(
        ("change", "error"),
        [
            # No longer a dataset: another kind of file in it.
            (
                lambda ds: (ds / "notes.txt").write_text("x"),
                "no longer matches Parquet",
            ),
            (lambda ds: [p.unlink() for p in ds.iterdir()] and ds.rmdir(), "is gone"),
        ],
    )
    def test_reload_of_an_item_changed_or_gone(self, tmp_path, change, error):
        pl = pytest.importorskip("polars")
        ds = tmp_path / "ds"
        ds.mkdir()
        pl.DataFrame({"a": [1]}).write_parquet(ds / "part-0.parquet")
        explorer = make(str(tmp_path))
        path = path_of(explorer, "ds")
        explorer.message({"type": "preview", "path": path})
        change(ds)
        reply = explorer.request({"type": "query_reload", "rid": 1, "path": path})
        assert error in reply["error"]

    def test_limits(self, tmp_path):
        (tmp_path / "a.txt").write_text("x" * 100)
        explorer = make(
            str(tmp_path), view_limits=ViewLimits(max_bytes=10, max_display_rows=7)
        )
        explorer.message({"type": "preview", "path": path_of(explorer, "a.txt")})
        [section] = explorer._preview["sections"]
        assert section["text"] == "x" * 10
        local = make(str(tmp_path), view_limits=ViewLimits(max_display_rows=7))
        (tmp_path / "d.csv").write_text("a\n1\n")
        local._list(local._current_dir)
        local.message({"type": "preview", "path": path_of(local, "d.csv")})
        assert local._preview["query"]["page_rows"] == 7  # the data browser's pages

    def test_preview_as_another_format(self, mem_explorer):
        mem_explorer._open_preview("/data/a.csv", "text")
        assert mem_explorer._preview["format"] == "text"
        mem_explorer._open_preview("/data/a.csv", "image")
        assert "cannot be previewed as image" in mem_explorer._preview["error"]

    def test_no_library_installed(self, memfs, monkeypatch):
        # No engine installed: an error, without calling the supports' view,
        # in the panel and for a tab.
        memfs.pipe_file("/data/a.csv", b"x,y\n1,2\n")
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        monkeypatch.setattr(CsvByPolars, "view", None)
        monkeypatch.setattr(CsvByPandas, "view", None)
        mem_explorer = make("/", fs=memfs)
        assert mem_explorer._engines == []
        mem_explorer._open_preview("/data/a.csv")
        # The engines come with plugins: which to install.
        assert mem_explorer._preview["error"] == (
            "a.csv cannot be viewed as CSV: no library viewing it is installed, "
            'e.g. pip install "jupyter-storage-explorer[polars]"'
        )
        reply = mem_explorer.request(
            {"type": "view_tab", "rid": 1, "path": "/data/a.csv"}
        )
        assert "no library viewing it is installed" in reply["error"]

    def test_query_after_close(self, local):
        reply = local.request({"type": "query_rows", "rid": 1, "path": "gone"})
        assert reply["error"].startswith("the data is no longer open")


def test_menu_info(mem_explorer):
    reply = mem_explorer.request({"type": "menu_info", "rid": 1, "path": "/data/a.csv"})
    assert reply["formats"] == ["csv", "text"]
    assert [(r["packages"], r["title"]) for r in reply["recipes"]] == [
        (["polars"], "Load as DataFrame"),
        (["pandas"], "Load as DataFrame"),
        (["pyspark"], "Load as DataFrame"),
    ]
    assert "query" not in reply  # known only once viewed
    folder = mem_explorer.request(
        {"type": "menu_info", "rid": 1, "path": "/data/table"}
    )
    assert folder["formats"] == ["delta"]


class SqliteByPython(FormatSupport):
    format = SQLite
    capabilities = ("recipe",)

    def recipe(self, fmt, ctx, options):
        return {"Connect": "import sqlite3"}


class DuckdbByPython(FormatSupport):
    format = DuckDB
    capabilities = ("recipe",)

    def recipe(self, fmt, ctx, options):
        return {"Connect": "import duckdb"}


class HeldText(FormatSupport):
    """Views text files once ``release`` is set, as a Spark session starting
    holds a view up; before the built-in views, as it is given first."""

    format = Text
    capabilities = ("view",)
    release = threading.Event()

    def view(self, fmt, ctx, options, limits):
        assert self.release.wait(5)
        return TextView(text=ctx.name)


class TestPreviewLoadsInTheBackground:
    """In a kernel, a preview's reads run in a worker thread: the panel shows
    "loading", and the explorer answers other messages meanwhile."""

    @pytest.fixture(autouse=True)
    def held(self):
        HeldText.release = threading.Event()
        yield
        HeldText.release.set()  # never leave a worker waiting

    @staticmethod
    def run(memfs, test):
        """Run ``test(explorer)`` in a running loop, as in a kernel."""
        memfs.pipe_file("/data/a.txt", b"a")
        memfs.pipe_file("/data/b.txt", b"b")

        async def main():
            return await test(make("/data", fs=memfs, supports=[HeldText]))

        return asyncio.run(main())

    def test_loading_then_the_view(self, memfs):
        async def test(explorer):
            explorer.message({"type": "preview", "path": "/data/a.txt"})
            assert explorer._preview["loading"]
            # The kernel is free: the explorer still lists folders.
            assert "error" not in explorer.request({"type": "list", "rid": 1})
            HeldText.release.set()
            await until(lambda: not explorer._preview.get("loading"))
            return explorer._preview

        preview = self.run(memfs, test)
        assert preview["format"] == "text"
        assert preview["sections"][0]["text"] == "a.txt"

    def test_the_latest_preview_wins(self, memfs, monkeypatch):
        closed = []
        monkeypatch.setattr(TextView, "close", lambda view: closed.append(view.text))

        async def test(explorer):
            explorer.message({"type": "preview", "path": "/data/a.txt"})
            explorer.message({"type": "preview", "path": "/data/b.txt"})
            HeldText.release.set()
            await until(lambda: not explorer._preview.get("loading"))
            await until(lambda: closed)
            return explorer._preview

        preview = self.run(memfs, test)
        assert preview["path"] == "/data/b.txt"
        assert closed == ["a.txt"]  # read, then closed: never shown

    def test_closing_the_panel_cancels_it(self, memfs, monkeypatch):
        closed = []
        monkeypatch.setattr(TextView, "close", lambda view: closed.append(view.text))

        async def test(explorer):
            explorer.message({"type": "preview", "path": "/data/a.txt"})
            explorer._preview = {}  # the frontend's close button
            HeldText.release.set()
            await until(lambda: closed)
            return explorer._preview

        assert self.run(memfs, test) == {}
        assert closed == ["a.txt"]

    def test_an_error_shows_in_the_panel(self, memfs, monkeypatch):
        def failing(self, fmt, ctx, options, limits):
            raise ValueError("no Spark")

        monkeypatch.setattr(HeldText, "view", failing)

        async def test(explorer):
            explorer.message({"type": "preview", "path": "/data/a.txt"})
            await until(lambda: not explorer._preview.get("loading"))
            return explorer._preview

        assert "no Spark" in self.run(memfs, test)["error"]


class TestClickDetectsOnce:
    """A click's selection, menu and preview share one detection of the item
    (``_detect``), until a refresh, a job's changes, another storage, or a
    few seconds later."""

    @pytest.fixture
    def infos(self, mem_explorer, monkeypatch):
        """The paths the storage was asked the info of."""
        asked = []
        info = mem_explorer._fs.info

        def counted(path, **kwargs):
            asked.append(path)
            return info(path, **kwargs)

        monkeypatch.setattr(mem_explorer._fs, "info", counted)
        return asked

    def click(self, explorer, path):
        explorer._selected = [path]
        explorer.request({"type": "menu_info", "rid": 1, "path": path})
        explorer.message({"type": "preview", "path": path})

    def test_one_detection(self, mem_explorer, infos):
        self.click(mem_explorer, "/data/a.csv")
        assert infos == ["/data/a.csv"]
        assert mem_explorer._preview["format"] == "csv"

    def test_forgotten_on_refresh(self, mem_explorer, infos):
        self.click(mem_explorer, "/data/a.csv")
        mem_explorer._invalidate_cache()
        self.click(mem_explorer, "/data/a.csv")
        assert len(infos) == 2

    def test_forgotten_after_a_while(self, mem_explorer, infos, monkeypatch):
        monkeypatch.setattr(previews, "_DETECTED_SECONDS", 0)
        self.click(mem_explorer, "/data/a.csv")
        assert len(infos) == 3

    def test_saved_file_detected_again(self, mem_explorer, infos):
        self.click(mem_explorer, "/data/a.csv")
        mem_explorer._write_bytes("/data/a.csv", b"x;y\n1;2\n")
        self.click(mem_explorer, "/data/a.csv")
        assert len(infos) == 2

    def test_other_items_detected(self, mem_explorer, infos):
        self.click(mem_explorer, "/data/a.csv")
        self.click(mem_explorer, "/data/notes.md")
        assert infos == ["/data/a.csv", "/data/notes.md"]


def test_signatures_decide_formats_once_clicked(memfs):
    # Two ".db" files: the listing reads neither, the menu reads each.
    memfs.pipe_file("/dbs/a.db", SQLITE_BYTES)
    memfs.pipe_file("/dbs/b.db", DUCKDB_BYTES)
    explorer = make("/dbs", fs=memfs, supports=[SqliteByPython, DuckdbByPython])
    assert {e["name"]: e["format"] for e in entries(explorer)} == {
        "a.db": "",
        "b.db": "",
    }
    for name, expected in [("a.db", ["sqlite"]), ("b.db", ["duckdb"])]:
        reply = explorer.request(
            {"type": "menu_info", "rid": 1, "path": f"/dbs/{name}"}
        )
        assert reply["formats"] == expected


class TestViewTab:
    """ "View in a new tab": a DataExplorer of the same query for data, else
    a ViewTab of the view."""

    def test_data_with_the_remembered_settings_and_closed(self, local):
        path = path_of(local, "data.parquet")
        url = local._url(path)
        local._states.remember_query(
            local._location_of(path), QuerySettings(sort="a", descending=True)
        )
        reply = local.request({"type": "view_tab", "rid": 1, "path": path})
        assert reply["title"] == "data.parquet" and reply["url"] == url
        tab = local._view_tabs[reply["model_id"]]
        assert isinstance(tab, DataExplorer)
        # Labelled with the file's format, as in the preview, not its library.
        assert (tab._height, tab._library) == ("fill", "Parquet · Polars")
        assert tab.settings.to_dict()["sort"] == {"column": "a", "descending": True}
        # Its settings are remembered by location, as the preview's.
        tab._data.handle(
            {
                "type": "query_save",
                "rid": 2,
                "settings": {"sort": None, "hidden": ["a"]},
            }
        )
        assert local._states.query(url).settings.to_dict()["hidden"] == ["a"]
        local.message({"type": "view_tab_closed", "model_id": reply["model_id"]})
        assert reply["model_id"] not in local._view_tabs

    def test_other_views_in_a_view_tab(self, local):
        path = path_of(local, "notes.txt")
        reply = local.request({"type": "view_tab", "rid": 1, "path": path})
        tab = local._view_tabs[reply["model_id"]]
        assert isinstance(tab, ViewTab)
        assert (tab.title, tab.label) == ("notes.txt", "Text")
        assert (tab.view["kind"], tab.view["text"]) == ("text", "hello\n")

    def test_view_tabs_load_markdown_libraries(self):
        tab = ViewTab(
            {"kind": "markdown", "text": "# x"}, title="a.md", label="Markdown"
        )
        sent = []
        tab.send = lambda content, buffers=None: sent.append(content)
        tab._on_custom_msg(
            tab, {"type": "vendor", "rid": 3, "name": "marked.esm.js"}, []
        )
        [reply] = sent
        assert (reply["type"], reply["rid"]) == ("reply", 3)
        assert "marked" in reply["source"]

    def test_refused_without_a_format(self, local):
        (local._fs).pipe_file(f"{local._root}/x.bin", b"\0")
        local._list(local._current_dir)
        reply = local.request(
            {"type": "view_tab", "rid": 1, "path": path_of(local, "x.bin")}
        )
        assert reply["error"] == "x.bin cannot be viewed in any format"
        assert not local._view_tabs


class TestClose:
    """Views are closed (``View.close``, calling their ``on_close``) once the
    explorer no longer shows them."""

    @pytest.fixture
    def closed(self, monkeypatch):
        """The titles of the views closed, each view titled by its number."""
        closed, count = [], itertools.count(1)
        view = SupportChain.view

        def closing(self, *args, **kwargs):
            viewed = dataclasses.replace(
                view(self, *args, **kwargs), title=str(next(count))
            )
            viewed.on_close(lambda v: closed.append(v.title))
            return viewed

        monkeypatch.setattr(SupportChain, "view", closing)
        return closed

    def test_preview_replaced(self, local, closed):
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        local.message({"type": "preview", "path": path_of(local, "data.parquet")})
        assert closed == ["1"]
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        assert closed == ["1", "2"]  # the data browser's view, with its query
        assert not local._queries

    def test_panel_closed_by_the_frontend(self, local, closed):
        local.message({"type": "preview", "path": path_of(local, "data.parquet")})
        local._preview = {}
        assert closed == ["1"]

    def test_reload_closes_the_previous_view_only(self, local, closed):
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path})
        local.request({"type": "query_reload", "rid": 1, "path": path})
        local.request({"type": "query_reload", "rid": 2, "path": path})
        assert closed == ["1", "2"]
        reply = local.request(
            {"type": "query_rows", "rid": 3, "path": path, "offset": 0, "window": 1}
        )
        assert reply["rows"] == [[1]]
        local._close_preview()
        assert closed == ["1", "2", "3"]

    def test_storage_switched(self, local, memfs, closed):
        explorer = make(filesystems={"local": local._root, "memory": memfs})
        explorer.message({"type": "preview", "path": path_of(explorer, "data.parquet")})
        explorer._filesystem = "memory"
        assert closed == ["1"]

    def test_view_tabs(self, local, closed):
        for name in ("notes.txt", "data.parquet"):
            reply = local.request(
                {"type": "view_tab", "rid": 1, "path": path_of(local, name)}
            )
            local.message({"type": "view_tab_closed", "model_id": reply["model_id"]})
        assert closed == ["1", "2"]

    def test_explorer_closed(self, local, closed):
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        local.request(
            {"type": "view_tab", "rid": 1, "path": path_of(local, "data.parquet")}
        )
        local.close()
        assert sorted(closed) == ["1", "2"]
        assert not local._view_tabs

    def test_kernel_exit(self, local, closed, monkeypatch):
        # Every explorer's views, the preview's and its tabs' (data and other
        # views), even after another explorer fails; no widget is closed, as
        # no message reaches the page then.
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        for name in ("data.parquet", "notes.txt"):
            local.request({"type": "view_tab", "rid": 1, "path": path_of(local, name)})
        failing = make(local._root)
        failing.message({"type": "preview", "path": path_of(failing, "notes.txt")})
        monkeypatch.setattr(failing, "_release_preview", lambda: 1 / 0, raising=False)
        previews._close_views_at_exit()
        assert sorted(closed) == ["1", "2", "3"]
        assert len(local._view_tabs) == 2  # still open, only released
        previews._close_views_at_exit()  # closing twice closes nothing more
        assert sorted(closed) == ["1", "2", "3"]

    def test_failed_preview_closes_its_view(self, local, closed, monkeypatch):
        def failing(*args, **kwargs):
            raise ValueError("cannot query")

        monkeypatch.setattr(previews.DataQuery, "__init__", failing)
        local.message({"type": "preview", "path": path_of(local, "data.parquet")})
        assert local._preview["error"] == "cannot query"
        assert closed == ["1"]


@pytest.mark.parametrize(
    ("counts", "note"),
    [
        ({}, "2 rows"),
        ({"more": True}, "First 2 rows"),
        ({"more": True, "total": 1234}, "First 2 of 1,234 rows"),
        ({"unit": "records", "note": "other sheets: b"}, "2 records; other sheets: b"),
    ],
)
def test_table_notes_worded_by_the_explorer(counts, note):
    table = TableView(columns=["a"], rows=[[1], [2]], **counts)
    assert previews.section(table)["note"] == note


def test_view_closed_once_and_errors_logged(caplog):
    calls = []
    view = TextView(text="x")
    record = calls.append
    view.on_close(lambda v: 1 / 0)
    view.on_close(record)
    view.on_close(record)  # once, however often given
    view.close()
    view.close()
    assert calls == [view]  # after the failing one, which was logged
    assert "Closing a text view failed" in caplog.text
    removed = TextView(text="x")
    removed.on_close(record)
    removed.on_close(record, remove=True)
    removed.close()
    assert calls == [view]
    assert previews.section(view) == {
        "kind": "text",
        "title": "",
        "note": "",
        "text": "x",
        "language": None,
        "html": None,
    }


def test_vendor(mem_explorer):
    assert (
        "marked"
        in mem_explorer.request({"type": "vendor", "rid": 1, "name": "marked.esm.js"})[
            "source"
        ]
    )
    assert (
        "unknown library"
        in mem_explorer.request({"type": "vendor", "rid": 1, "name": "../x"})["error"]
    )
