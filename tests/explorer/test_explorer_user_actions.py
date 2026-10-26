"""StorageExplorer's "Actions > Reload":the user's action files read again,
without creating the explorer again."""

from __future__ import annotations

import textwrap

import pytest
from explorers import entries, make

UPPER_CASE = """\
from jupyter_storage_explorer.formats import Text
from jupyter_storage_explorer.actions import view


@view(format=Text, label="Upper case")
def upper_case(fs, path):
    with fs.open(path, "rt") as f:
        return f.read().upper()
"""

ABC_FILES = """\
from jupyter_storage_explorer.formats import file_format
from jupyter_storage_explorer.actions import code


@code(format=file_format(".abc", label="ABC files", name="abc"))
def read_abc(url):
    return "abc"
"""


@pytest.fixture
def actions_file(tmp_path, jupyter_config_dirs):
    """The user's actions.py, in the user's configuration folder: written by
    the test after the explorer is created."""
    jupyter_config_dirs.append(str(tmp_path / "user"))
    path = tmp_path / "user" / "storage-explorer" / "actions.py"
    path.parent.mkdir(parents=True)
    return path


def write(path, source):
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def reload(explorer):
    return explorer.request({"type": "reload_actions", "rid": 1})


def labels(explorer):
    return [a.label for a in explorer._actions.actions]


class TestReload:
    def test_a_new_action(self, memfs, actions_file):
        explorer = make("/", fs=memfs, user_actions="enabled")
        assert "Upper case" not in labels(explorer)
        write(actions_file, UPPER_CASE)
        reply = reload(explorer)
        assert (reply["actions"], reply["problems"]) == (1, [])
        assert "Upper case" in labels(explorer)

    def test_an_action_removed(self, memfs, actions_file):
        write(actions_file, UPPER_CASE)
        explorer = make("/", fs=memfs, user_actions="enabled")
        write(actions_file, "")
        assert reload(explorer)["actions"] == 0
        assert "Upper case" not in labels(explorer)

    def test_a_new_format_listed(self, memfs, actions_file):
        # The folder is listed again with the new format, and the page told
        # of its label.
        memfs.pipe_file("/data/a.abc", b"x")
        explorer = make("/data", fs=memfs, user_actions="enabled")
        assert {e["name"]: e["format"] for e in entries(explorer)}["a.abc"] == ""
        write(actions_file, ABC_FILES)
        reload(explorer)
        assert {e["name"]: e["format"] for e in entries(explorer)}["a.abc"] == "abc"
        assert explorer._format_labels["abc"] == "ABC files"

    def test_a_broken_file_left_out(self, memfs, actions_file):
        # The other files' actions are used; the broken one is told.
        explorer = make("/", fs=memfs, user_actions="enabled")
        write(actions_file, UPPER_CASE)
        broken = actions_file.parent / "actions" / "broken.py"
        broken.parent.mkdir()
        write(broken, "def broken(:\n")
        reply = reload(explorer)
        assert reply["actions"] == 1
        [problem] = reply["problems"]
        assert "broken.py not loaded" in problem and "SyntaxError" in problem
        assert "Upper case" in labels(explorer)

    def test_the_engine_kept(self, memfs, actions_file):
        explorer = make("/", fs=memfs, user_actions="enabled")
        engine = explorer._engine
        write(actions_file, UPPER_CASE)
        reload(explorer)
        assert explorer._engine == engine
        assert engine in [e["key"] for e in explorer._engines]

    def test_not_with_user_actions_disabled(self, memfs, actions_file):
        write(actions_file, UPPER_CASE)
        explorer = make("/", fs=memfs, user_actions="disabled")
        assert reload(explorer) == {
            "type": "reply",
            "rid": 1,
            "error": "this explorer reads no actions files",
        }
        assert "Upper case" not in labels(explorer)
