"""TableSetView: several tables of one item, one chosen at a time in a tree or
on tabs and shown in the data browser (formats/view.py, _query/table_set.py,
the explorer's previews and view tabs, _table_set_tab.py)."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import make, path_of

from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._query.table_set import query_path
from jupyter_storage_explorer._table_set_tab import TableSetTab
from jupyter_storage_explorer.formats import Leaf, Node, QueryView, TableSetView

TABLES = {"a": pl.LazyFrame({"x": [1, 2, 3]}), "b": pl.LazyFrame({"y": ["p", "q"]})}


def leaves() -> list[Leaf]:
    return [Leaf(label=name.upper(), id=name) for name in [*TABLES, "broken"]]


class Tables:
    """A support's table sets, each viewed with its tables in ``nodes``:
    the tables it reads (``loaded``) and the views closed (``closed``)."""

    def __init__(self, selector: str = "tree") -> None:
        self.selector = selector
        self.loaded: list[str] = []
        self.closed = 0

    def load(self, table: str):
        self.loaded.append(table)
        if table == "broken":
            raise ValueError("cannot read broken")
        return TABLES[table]

    def close(self, view) -> None:
        self.closed += 1

    def view(self) -> TableSetView:
        nodes = leaves()
        if self.selector == "tree":
            nodes = [Node(label="main", children=nodes)]
        view = TableSetView(nodes=nodes, loader=self.load, selector=self.selector)
        view.on_close(self.close)
        return view


@pytest.fixture
def tables(monkeypatch):
    tables = Tables()
    monkeypatch.setattr(SupportChain, "view", lambda self, *args, **kw: tables.view())
    return tables


@pytest.fixture
def local(tmp_path):
    (tmp_path / "db.txt").write_text("tables", encoding="utf-8")
    return make(str(tmp_path))


def preview(explorer) -> tuple[str, dict]:
    """Preview db.txt: its path and the preview's table set."""
    path = path_of(explorer, "db.txt")
    explorer.message({"type": "preview", "path": path})
    return path, explorer._preview["table_set"]


def rows(explorer, path: str, table: str, **content) -> dict:
    return explorer.request(
        {
            "type": "query_rows",
            "rid": 1,
            "path": query_path(path, table),
            "offset": 0,
            "window": 10,
            **content,
        }
    )


def choose(explorer, path: str, table: str) -> dict:
    return explorer.request(
        {"type": "table_set_open", "rid": 1, "path": path, "table": table}
    )


class TestView:
    def test_tables_in_the_trees_order(self):
        view = TableSetView(
            nodes=[
                Node(label="s1", children=[Leaf(label="t1", id="1")]),
                Leaf(label="t2", id="2"),
                Node(
                    label="s2",
                    children=[Node(label="g", children=[Leaf(label="t3", id="3")])],
                ),
            ],
            loader=TABLES.__getitem__,
        )
        assert [leaf.id for leaf in view.leaves()] == ["1", "2", "3"]
        assert view.selector == "tree"

    def test_a_table_holds_no_tables(self):
        with pytest.raises(ValueError, match="cannot have children"):
            Leaf(label="t", id="t", children=[Leaf(label="u", id="u")])

    @pytest.mark.parametrize(
        ("nodes", "selector", "message"),
        [
            ([Node(label="g", children=leaves())], "tab", "tables .* only"),
            (leaves(), "list", "selector must be"),
            ([Node(label="empty")], "tree", "at least one table"),
            ([Leaf(label="a", id="a"), Leaf(label="A", id="a")], "tab", "unique: a"),
        ],
    )
    def test_refused(self, nodes, selector, message):
        with pytest.raises(ValueError, match=message):
            TableSetView(nodes=nodes, loader=TABLES.__getitem__, selector=selector)


class TestPreview:
    def test_the_first_table_at_first(self, local, tables):
        path, table_set = preview(local)
        assert table_set["selector"] == "tree"
        assert table_set["nodes"] == [
            {
                "label": "main",
                "children": [
                    {"label": "A", "id": "a"},
                    {"label": "B", "id": "b"},
                    {"label": "BROKEN", "id": "broken"},
                ],
            }
        ]
        assert table_set["table"] == "a"
        assert [c["name"] for c in table_set["query"]["columns"]] == ["x"]
        assert rows(local, path, "a")["rows"] == [[1], [2], [3]]
        assert tables.loaded == ["a"]

    def test_tabs(self, local, tables):
        tables.selector = "tab"
        _, table_set = preview(local)
        assert table_set["selector"] == "tab"
        assert [n["id"] for n in table_set["nodes"]] == ["a", "b", "broken"]

    def test_another_table_chosen(self, local, tables):
        path, _ = preview(local)
        reply = choose(local, path, "b")
        assert reply["table"] == "b"
        assert [c["name"] for c in reply["query"]["columns"]] == ["y"]
        assert rows(local, path, "b")["rows"] == [["p"], ["q"]]
        # The previous table's panel is never answered for, nor its settings
        # remembered for this one.
        assert "another table" in rows(local, path, "a")["error"]

    def test_a_table_that_cannot_be_read(self, local, tables):
        path, _ = preview(local)
        assert choose(local, path, "broken") == {
            "type": "reply",
            "rid": 1,
            "table": "broken",
            "error": "cannot read broken",
        }
        assert choose(local, path, "a")["table"] == "a"

    def test_unknown_table(self, local, tables):
        path, _ = preview(local)
        assert "no table" in choose(local, path, "z")["error"]

    def test_reload_reads_the_table_again(self, local, tables):
        path, _ = preview(local)
        local.request({"type": "query_reload", "rid": 1, "path": query_path(path, "a")})
        assert tables.loaded == ["a", "a"]

    def test_settings_remembered_by_table(self, local, tables):
        path, _ = preview(local)
        rows(local, path, "a", settings={"widths": {"x": 120}})
        choose(local, path, "b")
        reply = choose(local, path, "a")
        assert reply["query"]["settings"]["widths"] == {"x": 120}
        assert choose(local, path, "b")["query"]["settings"]["widths"] == {}

    def test_query_result_follows_the_table_chosen(self, local, tables):
        changes = []
        local.on_query_change(
            lambda e: changes.append((e.query_table, e.query_result()))
        )
        assert local.query_table is None
        path, _ = preview(local)
        assert local.query_table == "a"
        assert local.query_result().collect().columns == ["x"]
        choose(local, path, "b")
        assert local.query_table == "b"
        assert local.query_result().collect().columns == ["y"]
        choose(local, path, "broken")  # chosen, not read
        assert (local.query_table, local.query_result()) == ("broken", None)
        assert [
            (table, None if result is None else result.collect().columns)
            for table, result in changes
        ] == [("a", ["x"]), ("b", ["y"]), ("broken", None)]
        local._close_preview()
        assert local.query_table is None

    def test_no_query_table_for_other_views(self, local):
        local.message({"type": "preview", "path": path_of(local, "db.txt")})
        assert local._preview["sections"]  # text
        assert local.query_table is None

    def test_tables_given_as_query_views(self, local, tables, monkeypatch):
        """A loader's QueryView: its rows cut short (``more``) are noted as
        rows in memory are, and it is closed once its table is not shown."""
        closed = []

        def load(table):
            view = QueryView(data=TABLES[table].collect(), more=table == "a")
            view.on_close(lambda v: closed.append(table))
            return view

        monkeypatch.setattr(tables, "load", load)
        path, table_set = preview(local)
        assert table_set["query"]["mode"]["memory"]["cut"] is True
        reply = choose(local, path, "b")
        assert reply["query"]["mode"]["memory"]["cut"] is False
        assert closed == ["a"]
        local._close_preview()
        assert closed == ["a", "b"]

    def test_closed_with_the_preview(self, local, tables):
        preview(local)
        assert tables.closed == 0
        local._close_preview()
        assert tables.closed == 1
        assert not local._table_sets


class TestViewTab:
    @pytest.fixture
    def tab(self, local, tables, monkeypatch):
        reply = local.request(
            {"type": "view_tab", "rid": 1, "path": path_of(local, "db.txt")}
        )
        tab = local._view_tabs[reply["model_id"]]
        tab.sent = []
        monkeypatch.setattr(tab, "send", tab.sent.append)
        return tab

    def ask(self, tab, content):
        tab._on_custom_msg(tab, {"rid": 1, **content}, [])
        return tab.sent[-1]

    def test_tables_in_a_tab(self, local, tables, tab):
        assert isinstance(tab, TableSetTab)
        assert (tab.title, tab.tables["table"]) == ("db.txt", "a")
        reply = self.ask(tab, {"type": "table_set_open", "table": "b"})
        assert reply["table"] == "b"
        reply = self.ask(
            tab, {"type": "query_rows", "path": query_path("", "b"), "window": 5}
        )
        assert reply["rows"] == [["p"], ["q"]]
        assert (
            "another table"
            in self.ask(tab, {"type": "query_rows", "path": query_path("", "a")})[
                "error"
            ]
        )

    def test_closed_with_the_tab(self, local, tables, tab):
        local.message({"type": "view_tab_closed", "model_id": tab.model_id})
        assert tables.closed == 1
