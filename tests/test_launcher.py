"""The launcher's layered configuration: launcher.py files merged system to user."""

from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING

import pytest
from jupyter_storage_explorer_launcher import launcher
from jupyter_storage_explorer_launcher.launcher import LauncherError, load_settings

from jupyter_storage_explorer.filesystems import FsspecOperations
from jupyter_storage_explorer.formats import default_formats
from jupyter_storage_explorer.operations import FileSystemOperations

if TYPE_CHECKING:
    import pathlib


def layer(tmp_path: pathlib.Path, name: str, code: str) -> pathlib.Path:
    """A launcher.py in directory ``name``, with ``code``."""
    path = tmp_path / name / "storage-explorer" / "launcher.py"
    path.parent.mkdir(parents=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch) -> pathlib.Path:
    """The user's Jupyter configuration directory, where tabs keep their states
    file: a temporary one, not the real ~/.jupyter."""
    path = tmp_path / "jupyter-config"
    monkeypatch.setenv("JUPYTER_CONFIG_DIR", str(path))
    return path


def defaults() -> tuple:
    """The arguments of a tab's explorer without any launcher.py."""
    return (".",), {"height": "fill", "states": launcher.states_file()}


@pytest.fixture
def system(tmp_path):
    return layer(
        tmp_path,
        "system",
        """
        def filesystems():
            return {"Lake": "memory://lake", "Scratch": "memory://scratch"}

        def format_options():
            return {"polars_storage_options": {"a": 1}, "polars_delta_use_pyarrow": True}

        def parameters():
            return {"max_upload_bytes": 1000, "height": "500px"}

        def style():
            return ".system {}"
        """,
    )


class TestMerging:
    def test_no_files_is_the_folder_opened_on(self):
        settings = load_settings([])
        assert settings.explorer_arguments() == defaults()

    def test_user_over_system(self, tmp_path, system):
        user = layer(
            tmp_path,
            "user",
            """
            def filesystems():
                return {"Mine": "memory://mine", "Scratch": None, "Lake": "memory://other"}

            def format_options():
                return {"polars_storage_options": {"b": 2}}

            def parameters():
                return {"height": "fill"}

            def style():
                return ".user {}"
            """,
        )
        settings = load_settings([user, system])  # Jupyter's order: user first
        # By name: added, replaced, and removed with None.
        args, kwargs = settings.explorer_arguments()
        assert args == ()
        assert kwargs["filesystems"] == {
            "Lake": "memory://other",
            "Mine": "memory://mine",
        }
        # Top level only: the user's dict replaces the system's.
        assert settings.format_options == {
            "polars_storage_options": {"b": 2},
            "polars_delta_use_pyarrow": True,
        }
        assert kwargs["format_options"] == settings.format_options
        assert kwargs["max_upload_bytes"] == 1000 and kwargs["height"] == "fill"
        assert settings.style == ".system {}\n.user {}"
        assert settings.warnings == []

    def test_lists_come_first_then_the_defaults(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            from jupyter_storage_explorer.filesystems import FsspecOperations
            from jupyter_storage_explorer.formats import Csv

            def formats():
                return [Csv()]

            def operations():
                return [FsspecOperations()]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            from jupyter_storage_explorer.operations import FileSystemOperations
            from jupyter_storage_explorer.formats import Json

            def formats():
                return [Json()]

            def operations():
                return [FileSystemOperations()]
            """,
        )
        _, kwargs = load_settings([user, system]).explorer_arguments()
        names = [f.name for f in kwargs["formats"]]
        assert names[:2] == ["json", "csv"]  # the user's first
        assert names[2:] == [f.name for f in default_formats()]
        # The explorer tries the defaults after them.
        kinds = [type(o) for o in kwargs["operations"]]
        assert kinds == [FileSystemOperations, FsspecOperations]

    def test_transfer_policy_later_layers_first(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            def transfer_policy():
                return [{"rule": "deny", "src": "s3://.*"}]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def transfer_policy():
                return [{"rule": "allow", "src": "s3://public/.*"}]
            """,
        )
        _, kwargs = load_settings([user, system]).explorer_arguments()
        assert kwargs["transfer_policy"] == [
            {"rule": "allow", "src": "s3://public/.*"},
            {"rule": "deny", "src": "s3://.*"},
        ]
        policy = load_settings([user, system]).create_widget()._transfer_policy
        assert policy.allows("s3://public/a.csv", "browser:///a.csv")
        assert not policy.allows("s3://private/a.csv", "browser:///a.csv")

    def test_creates_the_explorer(self, tmp_path, memfs):
        memfs.mkdir("/lake")
        path = layer(
            tmp_path,
            "user",
            """
            def filesystems():
                return {"Lake": "memory://lake"}
            """,
        )
        explorer = load_settings([path]).create_widget()
        assert explorer._filesystem_names == ["Lake"]
        assert explorer._height == "fill"


class TestFinal:
    def test_final_settings_cannot_be_changed(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            def filesystems():
                return {"Lake": "memory://lake"}

            def parameters():
                return {"max_upload_bytes": 1000}

            def transfer_policy():
                return [{"rule": "deny", "dest": "browser:///.*"}]

            def final():
                return ["filesystems", "max_upload_bytes", "style", "transfer_policy"]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def filesystems():
                return {"Lake": None, "Mine": "memory://mine"}

            def transfer_policy():
                return [{"rule": "allow"}]

            def parameters():
                return {"max_upload_bytes": None, "height": "300px"}

            def style():
                return ".user {}"
            """,
        )
        settings = load_settings([user, system])
        assert settings.filesystems == {"Lake": "memory://lake"}
        assert settings.parameters == {"max_upload_bytes": 1000, "height": "300px"}
        assert settings.style == ""
        assert settings.transfer_policy == [{"rule": "deny", "dest": "browser:///.*"}]
        assert [w.split(": ", 1)[1] for w in settings.warnings] == [
            f"filesystems is ignored: it is final in {system}",
            f"transfer_policy is ignored: it is final in {system}",
            f"style is ignored: it is final in {system}",
            f"max_upload_bytes is ignored: it is final in {system}",
        ]
        assert all(w.startswith(str(user)) for w in settings.warnings)

    def test_final_applies_to_later_layers_only(self, tmp_path):
        path = layer(
            tmp_path,
            "user",
            """
            def parameters():
                return {"height": "300px"}

            def final():
                return ["height"]
            """,
        )
        settings = load_settings([path])
        assert settings.parameters == {"height": "300px"} and settings.warnings == []


class TestErrors:
    @pytest.mark.parametrize(
        ("code", "message"),
        [
            (
                "def parameters():\n    return {'hieght': 1}",
                "unknown parameter 'hieght'",
            ),
            (
                "def parameters():\n    return {'filesystems': {}}",
                "set by its own function",
            ),
            (
                "def parameters():\n    return {'transfer_policy': []}",
                "transfer_policy is set by its own function",
            ),
            (
                "def parameters():\n    return {'operations': []}",
                "operations is set by its own function",
            ),
            ("def parameters():\n    return {'path': '.'}", "set by the launcher"),
            ("def final():\n    return ['parameters']", "unknown setting 'parameters'"),
            (
                "def filesystems():\n    return ['a']",
                "filesystems() must return a dict",
            ),
            ("def formats():\n    return 'csv'", "formats() must return a list"),
            (
                "def filesystems():\n    raise KeyError('LAKE_URL')",
                "filesystems(): KeyError",
            ),
            ("filesystems = {}", "filesystems must be a function"),
            ("import nonexistent_module", "ModuleNotFoundError"),
        ],
    )
    def test_reported_with_the_file(self, tmp_path, code, message):
        path = layer(tmp_path, "user", code)
        with pytest.raises(LauncherError, match=re.escape(message)) as info:
            load_settings([path])
        assert str(info.value).startswith(str(path))


def test_old_launch_function_is_reported(tmp_path):
    path = layer(tmp_path, "user", "def launch():\n    return None")
    settings = load_settings([path])
    assert settings.warnings == [
        f"{path}: launch() is no longer used; set filesystems(), parameters() etc. "
        "instead (see the launcher's README)"
    ]
    assert settings.explorer_arguments() == defaults()


class TestStates:
    def test_a_file_in_the_users_config_directory(self, config_dir):
        assert launcher.states_file() == config_dir / "storage-explorer" / "states.json"
        explorer = load_settings([]).create_widget()
        assert config_dir.joinpath("storage-explorer").is_dir()  # created
        assert explorer._states.path == launcher.states_file().resolve()

    def test_shared_by_the_tabs(self):
        first = load_settings([]).create_widget()
        second = load_settings([]).create_widget()
        assert first._states is second._states

    @pytest.mark.parametrize("value", [None, "other.json"])
    def test_set_by_parameters(self, tmp_path, config_dir, value):
        path = layer(
            tmp_path, "user", f"def parameters():\n    return {{'states': {value!r}}}"
        )
        explorer = load_settings([path]).create_widget()
        assert not config_dir.exists()  # not created
        if value is None:
            assert explorer._states.path is None  # in memory
        else:
            assert explorer._states.path.name == "other.json"


@pytest.mark.parametrize(
    ("view", "folder"),
    [
        ('{"filesystem": "Lake", "folders": {"Lake": "/lake/raw"}}', "/lake/raw"),
        ('{"filesystem": "Lake", "folders": {"Lake": "/lake/gone"}}', "/lake"),
        ("not json", "/lake"),
        ("[1, 2]", "/lake"),
        (None, "/lake"),
    ],
)
def test_reopens_the_tabs_view(tmp_path, memfs, view, folder):
    """The view saved by the tab, as JSON; one that cannot be used is ignored."""
    memfs.pipe_file("/lake/raw/a.csv", b"")
    path = layer(
        tmp_path, "user", "def filesystems():\n    return {'Lake': 'memory:///lake'}"
    )
    explorer = launcher._create_explorer(load_settings([path]), view)
    assert explorer._current_dir == folder


def test_files_found_in_jupyters_order(tmp_path, monkeypatch):
    user = layer(tmp_path, "user", "")
    system = layer(tmp_path, "system", "")
    (tmp_path / "empty").mkdir()
    directories = [
        str(user.parent.parent),
        str(tmp_path / "empty"),
        str(system.parent.parent),
    ]
    monkeypatch.setattr(launcher, "jupyter_config_path", lambda: directories)
    assert launcher.find_launcher_files() == [user, system]
