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


@pytest.fixture(autouse=True)
def no_launched(monkeypatch):
    """No explorer launched in this "kernel" yet (see launch()'s reuse)."""
    monkeypatch.setattr(launcher, "_launched", {})


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

        def engine_options():
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

            def engine_options():
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
        assert settings.engine_options == {
            "polars": {
                "*": {"storage_options": {"b": 2}},
                "delta": {"use_pyarrow": True},
            },
            "pandas": {"csv": {"storage_options": {"c": 3}}},
        }
        assert kwargs["engine_options"] == settings.engine_options
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
            def engine_options():
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
            def engine_options():
                return {"polars": {"*": {"credential_provider": None}}}
            """,
        )
        settings = load_settings([user, team, system])
        merged = settings.engine_options["polars"]["*"]
        assert merged("here") == {
            "storage_options": {"at": "here"},
            "credential_provider": None,
        }
        assert settings.engine_options["polars"]["delta"] == {"use_pyarrow": True}

    def test_lists_come_first_then_the_defaults(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            from jupyter_storage_explorer.filesystems import FsspecOperations
            from jupyter_storage_explorer_pandas_support import csv_view

            def actions():
                return [csv_view]

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
            from jupyter_storage_explorer_pandas_support import json_lines_view

            def actions():
                return [json_lines_view]

            def operations():
                return [FileSystemOperations()]

            def filesystem_mappers():
                from jupyter_storage_explorer.filesystems import GCSMapper
                return [GCSMapper()]
            """,
        )
        _, kwargs = load_settings([user, system]).explorer_arguments()
        # The user's first; the explorer tries the defaults after them.
        names = [a.__name__ for a in kwargs["actions"]]
        assert names == ["json_lines_view", "csv_view"]
        kinds = [type(o) for o in kwargs["operations"]]
        assert kinds == [FileSystemOperations, FsspecOperations]
        mappers = [type(m).__name__ for m in kwargs["filesystem_mappers"]]
        assert mappers == ["GCSMapper", "S3Mapper"]

    def test_plugin_options_by_plugin_then_option(self, tmp_path):
        system = layer(
            tmp_path,
            "system",
            """
            def plugin_options():
                return {
                    "pandas-support": {"enabled": False},
                    "abfs-support": {"concurrency": 16, "priority": 1},
                }
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def plugin_options():
                return {"abfs-support": {"concurrency": 8}}
            """,
        )
        _, kwargs = load_settings([user, system]).explorer_arguments()
        assert kwargs["plugin_options"] == {
            "pandas-support": {"enabled": False},
            "abfs-support": {"concurrency": 8, "priority": 1},
        }
        # Without any: every plugin installed, with its defaults.
        assert "plugin_options" not in load_settings([]).explorer_arguments()[1]

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

    def test_the_side_panels_layout_over_the_parameters(self, tmp_path):
        path = layer(
            tmp_path,
            "user",
            """
            def parameters():
                return {"tree_view": "closed", "height": "500px", "max_upload_bytes": 5}
            """,
        )
        settings = load_settings([path])
        _, kwargs = settings.explorer_arguments(sidebar=True)
        assert kwargs == {
            "states": launcher.states_file(),
            "max_upload_bytes": 5,
            **launcher.SIDEBAR,
        }
        # The tab's keeps the parameters.
        assert settings.explorer_arguments()[1]["tree_view"] == "closed"
        explorer = launcher._create_explorer(settings, None, sidebar=True)
        assert (explorer._layout, explorer._tree_view, explorer._preview_panel) == (
            "sidebar",
            "disabled",
            "disabled",
        )
        assert explorer._settings_path  # "Edit configuration" there too


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
        """formats() is no longer used: formats are those of the actions."""
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
        assert "actions()" in warning

    def test_retired_supports_is_ignored_with_a_warning(self, tmp_path):
        """supports() is no longer used: FormatSupport classes gave way to
        actions. A layer having it, or naming it in final(), still works."""
        path = layer(
            tmp_path,
            "user",
            """
            def supports():
                return [object()]

            def final():
                return ["supports"]
            """,
        )
        settings = load_settings([path])
        assert settings.explorer_arguments() == defaults()
        [warning] = settings.warnings
        assert warning.startswith(
            f"{path}: supports() is no longer used and is ignored"
        )
        assert "actions()" in warning

    def test_format_options_is_engine_options(self, tmp_path):
        """format_options(), engine_options()' former name, is still taken,
        also in final()."""
        system = layer(
            tmp_path,
            "system",
            """
            def format_options():
                return {"polars": {"*": {"storage_options": {"a": 1}}}}

            def final():
                return ["format_options"]
            """,
        )
        user = layer(
            tmp_path,
            "user",
            """
            def engine_options():
                return {"polars": {"*": {"storage_options": {"b": 2}}}}
            """,
        )
        settings = load_settings([user, system])
        assert settings.engine_options == {
            "polars": {"*": {"storage_options": {"a": 1}}}
        }
        assert settings.warnings == [
            f"{user}: engine_options is ignored: it is final in {system}"
        ]

    def test_engine_options_and_format_options_in_one_file(self, tmp_path):
        path = layer(
            tmp_path,
            "system",
            """
            def engine_options():
                return {}

            def format_options():
                return {}
            """,
        )
        with pytest.raises(LauncherError, match="give engine_options\\(\\) only"):
            load_settings([path])

    def test_unsafe_mode_blocked_for_everyone(self, tmp_path):
        # An administrator's layer blocks folder operations; a user's cannot
        # turn them back on.
        system = layer(
            tmp_path,
            "system",
            """
            def parameters():
                return {"unsafe_mode": "blocked"}

            def final():
                return ["unsafe_mode"]
            """,
        )
        user = layer(
            tmp_path, "user", "def parameters():\n    return {'unsafe_mode': 'always'}"
        )
        settings = load_settings([user, system])
        assert settings.parameters["unsafe_mode"] == "blocked"
        assert settings.warnings == [
            f"{user}: unsafe_mode is ignored: it is final in {system}"
        ]
        assert settings.create_widget()._unsafe_policy == "blocked"

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
            ("def actions():\n    return 'csv'", "actions() must return a list"),
            (
                "def plugin_options():\n    return {'pandas-support': False}",
                "'pandas-support' must map option names to values",
            ),
            (
                "def parameters():\n    return {'plugin_options': {}}",
                "plugin_options is set by its own function",
            ),
            (
                # The flat options of versions before 0.14.
                "def engine_options():\n"
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


def user_layer(config_dir: pathlib.Path, code: str) -> pathlib.Path:
    """The user's launcher.py, the file the settings button opens, with ``code``."""
    path = launcher.user_launcher_file()
    assert path.parent.parent == config_dir
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


class TestUserErrors:
    """An error in the user's launcher.py leaves it out, so that the tab
    opens and the user can fix it; one in another file stops the tab."""

    def test_the_users_file_is_left_out(self, config_dir, system):
        user = user_layer(
            config_dir,
            """
            def filesystems():
                return {"Mine": "memory://mine"}

            def parameters():
                return {"hieght": 1}
            """,
        )
        settings = load_settings([user, system])
        assert settings.user_error.startswith(str(user))
        assert "unknown parameter 'hieght'" in settings.user_error
        # None of it applied, its filesystems neither.
        assert list(settings.filesystems) == ["Lake", "Scratch"]
        assert settings.files == [system]

    @pytest.mark.parametrize(
        "code",
        [
            "import nonexistent_module",
            "def filesystems():\n    raise KeyError('LAKE_URL')",
            "def final():\n    return ['nonsense']",
        ],
    )
    def test_any_error_of_the_users_file(self, config_dir, code):
        user = user_layer(config_dir, code)
        settings = load_settings([user])
        assert settings.user_error.startswith(str(user))
        assert settings.explorer_arguments() == defaults()

    def test_another_files_error_stops(self, tmp_path, config_dir):
        user = user_layer(config_dir, "")
        system = layer(tmp_path, "system", "def parameters():\n    return {'x': 1}")
        with pytest.raises(LauncherError, match="unknown parameter 'x'"):
            load_settings([user, system])

    def test_explorer_created_without_the_users_file(self, config_dir, system):
        # A value the explorer refuses: only known when it is created.
        user = user_layer(
            config_dir, "def parameters():\n    return {'layout': 'wide'}"
        )
        settings = load_settings([user, system])
        explorer = launcher._create_explorer(settings, None)
        assert explorer._filesystem_names == ["Lake", "Scratch"]
        assert settings.user_error.startswith(f"{user}: the explorer cannot be created")
        assert "Your launcher settings were left out" in explorer._error
        assert settings.files == [system]

    def test_explorer_not_created_without_the_users_file_either(self, tmp_path):
        system = layer(
            tmp_path, "system", "def parameters():\n    return {'layout': 'wide'}"
        )
        with pytest.raises(LauncherError, match="the explorer cannot be created"):
            launcher._create_explorer(load_settings([system]), None)

    @pytest.fixture
    def shown(self, monkeypatch):
        """What launch() displays."""
        shown = []
        monkeypatch.setattr("IPython.display.display", shown.append)
        return shown

    def test_launch_warns_and_opens(self, config_dir, monkeypatch, capsys, shown):
        user = user_layer(config_dir, "def parameters():\n    return {'hieght': 1}")
        monkeypatch.setattr(launcher, "find_launcher_files", lambda: [user])
        launcher.launch()
        assert len(shown) == 1
        assert "Your launcher settings were left out" in capsys.readouterr().err

    def test_launch_stops_plainly(self, tmp_path, monkeypatch, capsys, shown):
        system = layer(tmp_path, "system", "def parameters():\n    return {'x': 1}")
        monkeypatch.setattr(launcher, "find_launcher_files", lambda: [system])
        launcher.launch()
        assert shown == []
        err = capsys.readouterr().err
        assert err.startswith(f"Storage Explorer cannot open: {system}")
        assert "Traceback" not in err


class TestRelaunch:
    """A page reload runs launch() again in the same kernel: it shows the
    explorer it made before, as it was, unless the launcher.py files changed."""

    @pytest.fixture
    def shown(self, monkeypatch):
        shown = []
        monkeypatch.setattr("IPython.display.display", shown.append)
        return shown

    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        system = layer(tmp_path, "system", "def filesystems():\n    return {}")
        monkeypatch.setattr(launcher, "find_launcher_files", lambda: [system])
        return system

    def test_the_same_explorer_as_it_was(self, files, shown, capsys):
        launcher.launch()
        explorer = shown[0]
        explorer._selected = [explorer._root]
        launcher.launch()
        assert shown == [explorer, explorer]
        assert explorer._selected == [explorer._root]

    def test_a_new_one_once_the_files_changed(self, files, shown):
        launcher.launch()
        files.write_text("def parameters():\n    return {'height': '300px'}")
        launcher.launch()
        first, second = shown
        assert second is not first
        assert second._height == "300px"
        assert first.comm is None  # closed

    def test_a_new_one_if_it_was_closed(self, files, shown):
        launcher.launch()
        shown[0].close()
        launcher.launch()
        assert shown[1] is not shown[0]

    def test_the_side_panels_apart_from_a_tabs(self, files, shown):
        launcher.launch()
        launcher.launch(sidebar=True)
        launcher.launch()
        tab, side, again = shown
        assert side is not tab and again is tab
        assert side._layout == "sidebar"

    def test_its_view_tabs_released(self, files, shown, monkeypatch):
        launcher.launch()
        explorer = shown[0]
        closed = []

        class Tab:
            def close(self):
                closed.append(self)

        tab = Tab()
        explorer._view_tabs["model"] = tab
        launcher.launch()
        assert closed == [tab]
        assert explorer._view_tabs == {}

    def test_its_warnings_shown_again(self, tmp_path, monkeypatch, shown, capsys):
        user = layer(tmp_path, "user", "def launch():\n    return None")
        monkeypatch.setattr(launcher, "find_launcher_files", lambda: [user])
        launcher.launch()
        launcher.launch()
        assert capsys.readouterr().err.count("launch() is no longer used") == 2


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
