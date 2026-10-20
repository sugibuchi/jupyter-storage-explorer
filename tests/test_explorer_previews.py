"""StorageExplorer's previews, data browser, query tabs and right-click menu."""

from __future__ import annotations

from explorers import path_of

from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer.formats import Requirement
from jupyter_storage_explorer.formats.supports import CsvByPandas, CsvByPolars


class TestPreview:
    def test_text(self, local):
        local.message({"type": "preview", "path": path_of(local, "notes.txt")})
        assert local._preview["format"] == "text"
        [section] = local._preview["sections"]
        assert (section["kind"], section["text"]) == ("text", "hello\n")

    def test_queryable_data_opens_the_data_browser(self, local):
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

    def test_preview_as_another_format(self, mem_explorer):
        mem_explorer._open_preview("/data/a.csv", "text")
        assert mem_explorer._preview["format"] == "text"
        mem_explorer._open_preview("/data/a.csv", "image")
        assert "cannot be previewed as image" in mem_explorer._preview["error"]

    def test_install_hint(self, mem_explorer, monkeypatch):
        # Packages missing: the explorer tells what to install, without
        # calling the supports' preview.
        monkeypatch.setattr(Requirement, "is_installed", lambda self: False)
        monkeypatch.setattr(CsvByPolars, "preview", None)
        monkeypatch.setattr(CsvByPandas, "preview", None)
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
    packages = [r["packages"] for r in reply["recipes"]]
    assert packages == [["polars"], ["pandas"], ["pyspark"]]
    folder = mem_explorer.request(
        {"type": "menu_info", "rid": 1, "path": "/data/table"}
    )
    assert folder["formats"] == ["delta"]


class TestQueryTab:
    """ "Query data" in a new tab: a DataExplorer of the same query."""

    def test_opened_with_the_remembered_settings_and_closed(self, local):
        path = path_of(local, "data.parquet")
        url = local._url(path)
        local._states.remember_query(
            local._location_of(path), QuerySettings(sort="a", descending=True)
        )
        reply = local.request({"type": "query_tab", "rid": 1, "path": path})
        assert reply["title"] == "data.parquet" and reply["url"] == url
        tab = local._query_tabs[reply["model_id"]]
        # Labelled with the file's format, as in the preview, not its library.
        assert (tab.height, tab.library) == ("fill", "Parquet")
        assert tab.settings.to_dict()["sort"] == {"column": "a", "descending": True}
        # Its settings are remembered by URL, as the preview's.
        tab._data.handle(
            {
                "type": "query_save",
                "rid": 2,
                "settings": {"sort": None, "hidden": ["a"]},
            }
        )
        assert local._states.query(url).settings.to_dict()["hidden"] == ["a"]
        local.message({"type": "query_tab_closed", "model_id": reply["model_id"]})
        assert reply["model_id"] not in local._query_tabs

    def test_refused_for_what_cannot_be_queried(self, local):
        reply = local.request(
            {"type": "query_tab", "rid": 1, "path": path_of(local, "notes.txt")}
        )
        assert reply["error"] == "notes.txt cannot be queried"
        assert not local._query_tabs


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
