"""The launcher's layered configuration: launcher.py files merged system to user."""

from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING

import pytest
from jupyter_storage_explorer_launcher import launcher
from jupyter_storage_explorer_launcher.launcher import LauncherError, load_settings

from jupyter_storage_explorer.filesystems import FsspecOperations
from jupyter_storage_explorer.filesystems.operation import FileSystemOperations

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
            return {
                "polars": {
                    "*": {"storage_options": {"a": 1}},
                    "delta": {"use_pyarrow": True},
                },
            }

        def parameters():
            return {"max_upload_bytes": 1000, "height": "500px"}
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
                return {
                    "polars": {"*": {"storage_options": {"b": 2}}},
                    "pandas": {"csv": {"storage_options": {"c": 3}}},
                }

            def parameters():
                return {"height": "fill"}
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
        # Option by option, a value replaced whole (the user's storage
        # options replace the system's dict).
        assert settings.format_options == {
            "polars": {
                "*": {"storage_options": {"b": 2}},
                "delta": {"use_pyarrow": True},
            },
            "pandas": {"csv": {"storage_options": {"c": 3}}},
        }
        assert kwargs["format_options"] == settings.format_options
        assert kwargs["max_upload_bytes"] == 1000 and kwargs["height"] == "fill"
        assert settings.warnings == []

    def test_options_by_location_merged_option_by_option(self, tmp_path, system):
        # A later layer's function over the system's dicts, then the user's
        # dict over that function: the later layer's options still win,
        # option by option, for each location.
        team = layer(
            tmp_path,
            "team",
            """
            def format_options():
                return {
                    "polars": {
                        "*": lambda location: {"storage_options": {"at": location}},
                    },
                }
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def format_options():
                return {"polars": {"*": {"credential_provider": None}}}
            """,
        )
        settings = load_settings([user, team, system])
        merged = settings.format_options["polars"]["*"]
        assert merged("here") == {
            "storage_options": {"at": "here"},
            "credential_provider": None,
        }
        assert settings.format_options["polars"]["delta"] == {"use_pyarrow": True}

    def test_lists_come_first_then_the_defaults(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            from jupyter_storage_explorer.filesystems import FsspecOperations
            from jupyter_storage_explorer_pandas_support import CsvByPandas

            def supports():
                return [CsvByPandas]

            def operations():
                return [FsspecOperations()]

            def filesystem_mappers():
                from jupyter_storage_explorer.filesystems import S3Mapper
                return [S3Mapper()]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
            from jupyter_storage_explorer_pandas_support import JsonByPandas

            def supports():
                return [JsonByPandas()]

            def operations():
                return [FileSystemOperations()]

            def filesystem_mappers():
                from jupyter_storage_explorer.filesystems import GCSMapper
                return [GCSMapper()]
            """,
        )
        _, kwargs = load_settings([user, system]).explorer_arguments()
        # The user's first; the explorer tries the defaults after them.
        supports = [s if isinstance(s, type) else type(s) for s in kwargs["supports"]]
        assert [s.__name__ for s in supports] == ["JsonByPandas", "CsvByPandas"]
        kinds = [type(o) for o in kwargs["operations"]]
        assert kinds == [FileSystemOperations, FsspecOperations]
        mappers = [type(m).__name__ for m in kwargs["filesystem_mappers"]]
        assert mappers == ["GCSMapper", "S3Mapper"]

    def test_plugins_replaced_by_later_layers(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            def plugins():
                return ["polars-support", "pandas-support"]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def plugins():
                return ["pandas-support"]
            """,
        )
        assert load_settings([system]).explorer_arguments()[1]["plugins"] == [
            "polars-support",
            "pandas-support",
        ]
        _, kwargs = load_settings([user, system]).explorer_arguments()
        assert kwargs["plugins"] == ["pandas-support"]
        # Without any: every plugin installed (the explorer's default).
        assert "plugins" not in load_settings([]).explorer_arguments()[1]

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
                return ["filesystems", "max_upload_bytes", "transfer_policy"]
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
            """,
        )
        settings = load_settings([user, system])
        assert settings.filesystems == {"Lake": "memory://lake"}
        assert settings.parameters == {"max_upload_bytes": 1000, "height": "300px"}
        assert settings.transfer_policy == [{"rule": "deny", "dest": "browser:///.*"}]
        assert [w.split(": ", 1)[1] for w in settings.warnings] == [
            f"filesystems is ignored: it is final in {system}",
            f"transfer_policy is ignored: it is final in {system}",
            f"max_upload_bytes is ignored: it is final in {system}",
        ]
        assert all(w.startswith(str(user)) for w in settings.warnings)

    def test_retired_style_is_ignored_with_a_warning(self, tmp_path):
        """style() is no longer used: a layer having it, or naming it in
        final(), still works, with a warning in the tab."""
        path = layer(
            tmp_path,
            "user",
            """
            def style():
                return ".jse-browser {}"

            def final():
                return ["style"]
            """,
        )
        settings = load_settings([path])
        assert settings.explorer_arguments() == defaults()
        [warning] = settings.warnings
        assert warning.startswith(f"{path}: style() is no longer used and is ignored")
        assert "custom.css" in warning

    def test_retired_formats_is_ignored_with_a_warning(self, tmp_path):
        """formats() is no longer used: formats are those of the supports."""
        path = layer(
            tmp_path,
            "user",
            """
            def formats():
                return []
            """,
        )
        settings = load_settings([path])
        assert settings.explorer_arguments() == defaults()
        [warning] = settings.warnings
        assert warning.startswith(f"{path}: formats() is no longer used and is ignored")
        assert "supports()" in warning

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
            ("def supports():\n    return 'csv'", "supports() must return a list"),
            (
                "def plugins():\n    return 'polars'",
                "plugins() must return a list of names",
            ),
            (
                "def parameters():\n    return {'plugins': []}",
                "plugins is set by its own function",
            ),
            (
                # The flat options of versions before 0.14.
                "def format_options():\n"
                "    return {'polars_storage_options': {'anon': True}}",
                "'polars_storage_options' must map format names",
            ),
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


class TestUserFile:
    """The file the tab's settings button opens: the user's launcher.py."""

    def test_offered_to_the_tabs_explorer(self, config_dir):
        explorer = launcher._create_explorer(load_settings([]), None)
        path = config_dir / "storage-explorer" / "launcher.py"
        assert explorer._settings_path == str(path)
        assert not path.exists()  # created when the button is clicked

    def test_created_from_the_template(self, config_dir):
        path = launcher.create_user_launcher_file()
        assert path == config_dir / "storage-explorer" / "launcher.py"
        assert "def filesystems():" in path.read_text(encoding="utf-8")
        # As created, it changes nothing.
        settings = load_settings([path])
        assert settings.explorer_arguments() == defaults()
        assert settings.warnings == []

    def test_an_existing_file_is_kept(self, config_dir):
        path = config_dir / "storage-explorer" / "launcher.py"
        path.parent.mkdir(parents=True)
        path.write_text("# mine\n", encoding="utf-8")
        assert launcher.create_user_launcher_file() == path
        assert path.read_text(encoding="utf-8") == "# mine\n"
