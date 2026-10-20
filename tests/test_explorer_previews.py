"""StorageExplorer's previews, data browser, view tabs and right-click menu."""

from __future__ import annotations

from explorers import make, path_of

from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer._view_tab import ViewTab
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.formats import Requirement, SupportChain, ViewLimits
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

    def test_install_hint(self, mem_explorer, monkeypatch):
        # Packages missing: the explorer tells what to install, without
        # calling the supports' view.
        monkeypatch.setattr(Requirement, "is_installed", lambda self: False)
        monkeypatch.setattr(CsvByPolars, "view", None)
        monkeypatch.setattr(CsvByPandas, "view", None)
        mem_explorer._open_preview("/data/a.csv")
        [hint] = mem_explorer._preview["sections"]
        assert hint["kind"] == "install"
        assert hint["options"] == [["polars"], ["pandas"]]

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
        assert (tab.height, tab.library) == ("fill", "Parquet")
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
