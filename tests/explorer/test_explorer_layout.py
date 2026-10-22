"""The explorer's layout: the folder tree (tree_view), the preview panel
(preview_panel), the sidebar layout (layout) and the list's columns."""

from __future__ import annotations

import pytest
import traitlets
from explorers import make

from jupyter_storage_explorer._explorer.states import ExplorerStates


def test_defaults(memfs):
    explorer = make("/", fs=memfs)
    assert (explorer._tree_view, explorer._preview_panel, explorer._layout) == (
        "open",
        "closed",
        "standard",
    )
    assert explorer._preview == {}


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("tree_view", "hidden"),
        ("preview_panel", True),
        ("layout", "narrow"),
    ],
)
def test_unknown_values_are_refused(memfs, argument, value):
    with pytest.raises(ValueError, match=argument):
        make("/", fs=memfs, **{argument: value})


def test_preview_panel_open_starts_empty(memfs):
    explorer = make("/", fs=memfs, preview_panel="open")
    assert explorer._preview == {"empty": True}


def test_open_preview_is_deprecated(memfs):
    with pytest.warns(DeprecationWarning, match="preview_panel"):
        explorer = make("/", fs=memfs, open_preview=True)
    assert explorer._preview_panel == "open"
    assert explorer._preview == {"empty": True}


class TestTree:
    def test_opened_and_closed_by_the_frontend(self, memfs):
        explorer = make("/", fs=memfs, tree_view="closed")
        explorer.set_state({"_tree_view": "open"})
        assert explorer._tree_view == "open"
        explorer.set_state({"_tree_view": "closed"})
        assert explorer._tree_view == "closed"

    def test_disabled_stays_disabled(self, memfs):
        explorer = make("/", fs=memfs, tree_view="disabled")
        with pytest.raises(traitlets.TraitError):
            explorer.set_state({"_tree_view": "open"})
        assert explorer._tree_view == "disabled"

    def test_cannot_be_disabled_later(self, memfs):
        explorer = make("/", fs=memfs)
        with pytest.raises(traitlets.TraitError):
            explorer.set_state({"_tree_view": "disabled"})


class TestPreviewDisabled:
    def test_previews_are_not_opened(self, memfs):
        memfs.pipe_file("/a.txt", b"hello")
        explorer = make("/", fs=memfs, preview_panel="disabled")
        explorer.message({"type": "preview", "path": "/a.txt"})
        assert explorer._preview == {}

    def test_items_are_still_viewed_in_tabs(self, memfs):
        memfs.pipe_file("/a.txt", b"hello")
        explorer = make("/", fs=memfs, preview_panel="disabled")
        reply = explorer.view_tab("/a.txt")
        assert "error" not in reply
        assert reply["model_id"] in explorer._view_tabs


class TestColumns:
    def test_defaults_by_layout(self, memfs):
        assert make("/", fs=memfs)._columns == ["size", "mtime"]
        assert make("/", fs=memfs, layout="sidebar")._columns == ["size"]

    def test_chosen_columns_remembered_by_layout(self, memfs):
        states = ExplorerStates()
        explorer = make("/", fs=memfs, states=states)
        explorer.set_state({"_columns": ["format", "size", "owner"]})
        # In the list's order, without columns it does not have.
        assert explorer._columns == ["size", "format"]
        assert make("/", fs=memfs, states=states)._columns == ["size", "format"]
        sidebar = make("/", fs=memfs, states=states, layout="sidebar")
        assert sidebar._columns == ["size"]

    def test_none_at_all(self, memfs):
        states = ExplorerStates()
        make("/", fs=memfs, states=states).set_state({"_columns": []})
        assert make("/", fs=memfs, states=states)._columns == []


def test_sidebar_layout(memfs):
    explorer = make(
        "/", fs=memfs, layout="sidebar", tree_view="disabled", preview_panel="disabled"
    )
    assert explorer._layout == "sidebar"
