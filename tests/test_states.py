"""_explorer/states.py: bookmarks and the data browser's recent queries, kept in memory or in a file."""

from __future__ import annotations

import json

import pytest

from jupyter_storage_explorer._explorer.states import (
    Bookmark,
    ExplorerStates,
    QueryState,
    default_states,
    explorer_states,
)
from jupyter_storage_explorer._query.settings import QuerySettings

SORTED = QuerySettings(sort="a", descending=True)


class TestFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "sub" / "states.json"
        states = ExplorerStates(path)
        states.add_bookmark("Lake", "bucket/data", "s3://bucket/data")
        states.remember_query("s3://bucket/data/x.parquet", SORTED, "live")
        again = ExplorerStates(path)
        assert again.bookmarks == [Bookmark("Lake", "bucket/data", "s3://bucket/data")]
        assert again.queries == [
            QueryState("s3://bucket/data/x.parquet", SORTED, "live")
        ]
        assert [p.name for p in path.parent.iterdir()] == [
            "states.json"
        ]  # no temp file left

    def test_reload_reads_changes_made_elsewhere(self, tmp_path):
        path = tmp_path / "states.json"
        mine, other = ExplorerStates(path), ExplorerStates(path)
        other.add_bookmark("default", "/data")
        assert mine.bookmarks == []
        mine.reload()
        assert mine.bookmarks == [Bookmark("default", "/data")]

    def test_missing_file_is_empty(self, tmp_path):
        states = ExplorerStates(tmp_path / "none.json")
        assert (states.bookmarks, states.queries) == ([], [])
        assert not (tmp_path / "none.json").exists()  # written at the first change

    def test_other_keys_kept(self, tmp_path):
        path = tmp_path / "states.json"
        path.write_text(json.dumps({"bookmarks": [], "later": {"x": 1}}))
        ExplorerStates(path).add_bookmark("default", "/data")
        assert json.loads(path.read_text())["later"] == {"x": 1}

    def test_entries_that_cannot_be_used_are_left_out(self, tmp_path):
        path = tmp_path / "states.json"
        path.write_text(
            json.dumps(
                {
                    "bookmarks": [{"filesystem": "a", "path": "/x"}, {"path": "/y"}, 3],
                    "queries": [
                        {"url": "u1", "settings": {"sort": "not a dict"}},
                        {"url": "u2", "mode": "sideways"},
                        {"settings": {}},
                    ],
                }
            )
        )
        states = ExplorerStates(path)
        assert states.bookmarks == [Bookmark("a", "/x")]
        assert states.queries == [QueryState("u2", QuerySettings(), "auto")]

    def test_changes_made_elsewhere_are_kept(self, tmp_path):
        """Each kernel (e.g. each launcher tab) has its own states of the
        file: a change is made to the file as it is now, not as read before."""
        path = tmp_path / "states.json"
        first, second = ExplorerStates(path), ExplorerStates(path)
        first.add_bookmark("a", "/x")
        second.add_bookmark("a", "/y")
        second.remember_query("u", SORTED)
        first.remove_bookmark("a", "/never")
        assert ExplorerStates(path).bookmarks == [
            Bookmark("a", "/x"),
            Bookmark("a", "/y"),
        ]
        assert [q.url for q in ExplorerStates(path).queries] == ["u"]

    def test_unreadable_file_not_written_over(self, tmp_path):
        path = tmp_path / "states.json"
        states = ExplorerStates(path)
        path.write_text("{typo")
        states.add_bookmark("a", "/x")
        assert states.bookmarks == [Bookmark("a", "/x")]  # in memory
        assert path.read_text() == "{typo"

    @pytest.mark.parametrize("text", ["[]", "{not json"])
    def test_not_a_json_object(self, tmp_path, text):
        path = tmp_path / "states.json"
        path.write_text(text)
        with pytest.raises(ValueError, match=r"states\.json"):
            ExplorerStates(path)


class TestBookmarks:
    def test_added_in_order_once(self):
        states = ExplorerStates()
        states.add_bookmark("a", "/x")
        states.add_bookmark("a", "/y")
        states.add_bookmark("a", "/x", "file:///x")  # keeps its place, gets the URL
        assert states.bookmarks == [
            Bookmark("a", "/x", "file:///x"),
            Bookmark("a", "/y"),
        ]

    def test_removed(self):
        states = ExplorerStates()
        states.add_bookmark("a", "/x")
        states.add_bookmark("b", "/x")
        states.remove_bookmark("a", "/x")
        states.remove_bookmark("a", "/never")
        assert states.bookmarks == [Bookmark("b", "/x")]

    def test_list_is_a_copy(self):
        states = ExplorerStates()
        states.bookmarks.append(Bookmark("a", "/x"))
        assert states.bookmarks == []


class TestQueries:
    def test_most_recent_first(self):
        states = ExplorerStates()
        for url in ("u1", "u2", "u1"):
            states.remember_query(url, SORTED)
        assert [q.url for q in states.queries] == ["u1", "u2"]

    def test_least_recent_forgotten_beyond_the_limit(self):
        states = ExplorerStates(max_queries=2)
        for url in ("u1", "u2", "u3"):
            states.remember_query(url, SORTED)
        assert [q.url for q in states.queries] == ["u3", "u2"]
        assert states.query("u1") is None

    def test_updated_in_place(self):
        states = ExplorerStates()
        states.remember_query("u", SORTED)
        states.remember_query("u", QuerySettings(hidden=["b"]), "memory")
        assert states.queries == [
            QueryState("u", QuerySettings(hidden=["b"]), "memory")
        ]

    def test_defaults_forgotten(self):
        states = ExplorerStates()
        states.remember_query("u", SORTED)
        states.remember_query("u", QuerySettings())
        assert states.query("u") is None
        # Default settings with a mode chosen are worth remembering.
        states.remember_query("u", QuerySettings(), "live")
        assert states.query("u").mode == "live"

    def test_forget(self):
        states = ExplorerStates()
        states.remember_query("u", SORTED)
        states.forget_query("u")
        assert states.queries == []

    def test_returns_copies(self):
        states = ExplorerStates()
        states.remember_query("u", QuerySettings(hidden=["a"]))
        states.query("u").settings.hidden.append("b")
        assert states.query("u").settings.hidden == ["a"]

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            ExplorerStates().remember_query("u", SORTED, "sideways")


class TestExplorerStates:
    """explorer_states: what StorageExplorer's ``states`` argument gives."""

    def test_default_and_objects(self):
        states = ExplorerStates()
        assert explorer_states(None) is default_states
        assert explorer_states(states) is states

    def test_one_per_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        by_path = explorer_states(tmp_path / "states.json")
        assert explorer_states("states.json") is by_path  # relative, as str
        assert by_path.path == (tmp_path / "states.json").resolve()
        assert explorer_states(tmp_path / "other.json") is not by_path

    def test_unreadable_file(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{typo")
        states = explorer_states(path)  # no error: the explorer reports it
        assert states.bookmarks == []
        states.add_bookmark("a", "/x")
        assert path.read_text() == "{typo"


def test_max_queries_at_least_one():
    with pytest.raises(ValueError, match="max_queries"):
        ExplorerStates(max_queries=0)
