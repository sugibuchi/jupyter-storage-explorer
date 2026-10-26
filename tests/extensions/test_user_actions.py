"""_extensions/user_actions.py: the actions of the user's files, storage-explorer/actions/*.py
in Jupyter's configuration folders, which every explorer loads."""

from __future__ import annotations

import importlib.resources
import textwrap

import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._extensions.user_actions import load_user_actions
from jupyter_storage_explorer.formats import Csv
from jupyter_storage_explorer.views import ViewLimits

# A user's file: an action of its own, and one imported (a built-in), which
# is not the file's.
SHOUT = """\
from jupyter_storage_explorer.formats import Text
from jupyter_storage_explorer.views import TextView
from jupyter_storage_explorer.actions import view
from jupyter_storage_explorer.actions.python import PythonEngine, text_view


@view(format=Text, engine=PythonEngine, label="Shout{suffix}")
def shout(fmt, ctx, options, limits):
    return TextView(text=ctx.head_text(100)[0].upper())
"""


def actions_dir(root, name="user"):
    folder = root / name / "storage-explorer" / "actions"
    folder.mkdir(parents=True)
    return folder


def write(folder, name, source):
    (folder / name).write_text(textwrap.dedent(source), encoding="utf-8")


def labels(actions):
    return [a.label for a in actions]


@pytest.fixture
def user(tmp_path, jupyter_config_dirs):
    """The user's actions folder, the first configuration folder."""
    folder = actions_dir(tmp_path)
    jupyter_config_dirs.append(str(tmp_path / "user"))
    return folder


class TestFiles:
    def test_top_level_actions_not_those_imported(self, user):
        write(user, "shout.py", SHOUT.format(suffix=""))
        actions, problems = load_user_actions()
        assert (labels(actions), problems) == (["Shout"], [])

    def test_the_users_first_then_by_name(self, tmp_path, user, jupyter_config_dirs):
        system = actions_dir(tmp_path, "system")
        jupyter_config_dirs.append(str(tmp_path / "system"))
        write(system, "a.py", SHOUT.format(suffix=" (system)"))
        write(user, "b.py", SHOUT.format(suffix=" (b)"))
        write(user, "a.py", SHOUT.format(suffix=" (a)"))
        write(user, "_helpers.py", "raise RuntimeError('not an actions file')")
        actions, problems = load_user_actions()
        assert labels(actions) == ["Shout (a)", "Shout (b)", "Shout (system)"]
        assert problems == []

    def test_actions_py_before_the_folder(self, user):
        # storage-explorer/actions.py, then storage-explorer/actions/*.py.
        write(user, "a.py", SHOUT.format(suffix=" (folder)"))
        write(user.parent, "actions.py", SHOUT.format(suffix=" (file)"))
        actions, _ = load_user_actions()
        assert labels(actions) == ["Shout (file)", "Shout (folder)"]

    def test_actions_given_as_ACTIONS(self, user):
        source = SHOUT.format(suffix="") + textwrap.dedent("""\

            @view(format=Text, engine=PythonEngine, label="Whisper")
            def whisper(fmt, ctx, options, limits):
                return TextView(text="")


            ACTIONS = [whisper]  # in this order, without shout
            """)
        write(user, "both.py", source)
        actions, _ = load_user_actions()
        assert labels(actions) == ["Whisper"]

    @pytest.mark.parametrize(
        ("source", "error"),
        [
            ("def broken(:\n", "SyntaxError"),
            ("raise RuntimeError('no')\n", "RuntimeError: no"),
            ("ACTIONS = ['shout']\n", "ACTIONS must be a sequence of actions"),
        ],
    )
    def test_a_file_that_cannot_be_used(self, user, source, error):
        write(user, "a_broken.py", source)
        write(user, "b.py", SHOUT.format(suffix=""))
        actions, problems = load_user_actions()
        assert labels(actions) == ["Shout"]  # the others are used
        [problem] = problems
        assert "a_broken.py not loaded" in problem
        assert error in problem

    def test_a_label_taken(self, user):
        write(user, "a.py", SHOUT.format(suffix=""))
        write(user, "b.py", SHOUT.format(suffix=""))  # the same label
        actions, problems = load_user_actions()
        assert labels(actions) == ["Shout"]
        assert (
            "b.py not loaded: ValueError: two actions labelled 'Shout'" in (problems[0])
        )

    def test_options_of_the_files_own(self, user, memfs):
        write(
            user,
            "csv.py",
            """\
            from dataclasses import dataclass

            from jupyter_storage_explorer.actions import ActionOptions
            from jupyter_storage_explorer.formats import Csv
            from jupyter_storage_explorer.views import TextView
            from jupyter_storage_explorer.actions import view
            from jupyter_storage_explorer.actions.python import PythonEngine


            @dataclass(frozen=True, kw_only=True)
            class RowsOptions(ActionOptions):
                rows: int = 1


            @view(format=Csv, engine=PythonEngine, label="Rows")
            def rows(fmt, ctx, options: RowsOptions, limits):
                return TextView(text=str(options.rows))
            """,
        )
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, engine_options={"python": {"csv": {"rows": 5}}}
        )
        item = explorer._detect_now("/a.csv", memfs)
        view = explorer._actions.view(Csv(), item.ctx, ViewLimits(), None)
        assert view.text == "5"


class TestTemplate:
    """actions_template.py, which "Edit actions" creates actions.py from."""

    def source(self):
        template = importlib.resources.files("jupyter_storage_explorer._extensions")
        return template.joinpath("actions_template.py").read_text(encoding="utf-8")

    def test_no_actions_as_it_is(self, user):
        (user.parent / "actions.py").write_text(self.source(), encoding="utf-8")
        assert load_user_actions() == ([], [])

    def test_its_example_uncommented(self, user):
        # The commented lines after the imports, uncommented, give its actions.
        lines = self.source().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("from "))
        code = "\n".join(line.removeprefix("# ") for line in lines[start:])
        (user.parent / "actions.py").write_text(code + "\n", encoding="utf-8")
        actions, problems = load_user_actions()
        assert (labels(actions), problems) == (["Upper case", "Pretty print json"], [])


class TestExplorer:
    def test_after_those_given(self, user, memfs):
        write(user, "shout.py", SHOUT.format(suffix=""))
        explorer = StorageExplorer(fs=memfs)
        assert "Shout" in labels(explorer._actions.actions)

    def test_not_used(self, user, memfs):
        write(user, "shout.py", SHOUT.format(suffix=""))
        explorer = StorageExplorer(fs=memfs, user_actions="disabled")
        assert "Shout" not in labels(explorer._actions.actions)

    @pytest.mark.parametrize("setting", [True, False, "on", None])
    def test_enabled_or_disabled(self, memfs, setting):
        with pytest.raises(ValueError, match="user_actions must be one of"):
            StorageExplorer(fs=memfs, user_actions=setting)

    def test_a_file_left_out_with_a_warning(self, user, memfs):
        write(user, "broken.py", "raise RuntimeError('no')\n")
        with pytest.warns(RuntimeWarning, match=r"broken\.py not loaded"):
            StorageExplorer(fs=memfs)

    def test_a_label_of_the_explorers_actions(self, user, memfs):
        # The explorer's own actions win: the file is left out.
        write(user, "shout.py", SHOUT.format(suffix=""))
        source = SHOUT.format(suffix="").replace("def shout", "def given")
        namespace: dict = {}
        exec(compile(source, "given", "exec"), namespace)
        with pytest.warns(RuntimeWarning, match="two actions labelled 'Shout'"):
            explorer = StorageExplorer(fs=memfs, actions=[namespace["given"]])
        assert labels(explorer._actions.actions).count("Shout") == 1
