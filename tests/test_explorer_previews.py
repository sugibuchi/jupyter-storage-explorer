"""StorageExplorer's previews, data browser, view tabs and right-click menu."""

from __future__ import annotations

import dataclasses
import itertools

import pytest
from explorers import make, path_of

from jupyter_storage_explorer._explorer import previews
from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer._view_tab import ViewTab
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import (
    PythonPackage,
    TableView,
    TextView,
    ViewLimits,
)
from jupyter_storage_explorer.formats.supports import CsvByPandas, CsvByPolars


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

    def test_no_library_installed(self, mem_explorer, monkeypatch):
        # No support installed for the format: an error, without calling the
        # supports' view, in the panel and for a tab.
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        monkeypatch.setattr(CsvByPolars, "view", None)
        monkeypatch.setattr(CsvByPandas, "view", None)
        mem_explorer._open_preview("/data/a.csv")
        assert mem_explorer._preview["error"] == (
            "a.csv cannot be viewed as CSV: no library viewing it is installed"
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
        assert (tab._height, tab._library) == ("fill", "Parquet")
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
