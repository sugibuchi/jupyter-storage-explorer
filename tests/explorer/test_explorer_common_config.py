"""Explorers in notebooks configured by the common.py files, under their own
arguments (see _extensions/config.py)."""

from __future__ import annotations

import pathlib
import textwrap
import warnings

import pytest
from explorers import make

from jupyter_storage_explorer._extensions.config import ConfigError, user_common_file


@pytest.fixture
def common(tmp_path, jupyter_config_dirs):
    """Writes a common.py in configuration directory ``name``, appended to
    the folders read: the user's first, so the last written is the system's."""

    def write(name: str, code: str) -> pathlib.Path:
        path = tmp_path / name / "storage-explorer" / "common.py"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(code), encoding="utf-8")
        jupyter_config_dirs.append(str(tmp_path / name))
        return path

    return write


@pytest.fixture
def user_common(jupyter_config_dirs):
    """Writes the user's common.py, in the user's configuration directory."""

    def write(code: str) -> pathlib.Path:
        path = user_common_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(code), encoding="utf-8")
        jupyter_config_dirs.insert(0, str(path.parent.parent))
        return path

    return write


def test_settings_under_the_arguments(common, memfs):
    common(
        "system",
        """
        def parameters():
            return {"height": "500px", "max_upload_bytes": 5, "tree_view": "closed"}

        def engine_options():
            return {"polars": {"*": {"storage_options": {"a": 1}}, "csv": {"separator": ";"}}}

        def transfer_policy():
            return [{"rule": "deny", "src": "memory://.*"}]
        """,
    )
    explorer = make(
        "/",
        fs=memfs,
        height="300px",
        engine_options={"polars": {"csv": {"has_header": False}}},
        transfer_policy=[{"rule": "allow", "src": "memory:///open/.*"}],
    )
    assert explorer._height == "300px"
    assert explorer._tree_view == "closed"
    assert explorer._incoming.max_bytes == 5
    # Merged option by option, as a later file's.
    engine_options = explorer._chain_options[0]["polars"]
    assert engine_options["*"] == {"storage_options": {"a": 1}}
    assert engine_options["csv"] == {"separator": ";", "has_header": False}
    # The arguments' rules first.
    policy = explorer._transfer_policy
    assert policy.allows("memory:///open/a.csv", "browser:///a.csv")
    assert not policy.allows("memory:///other/a.csv", "browser:///a.csv")


def test_the_files_storages_without_a_path(common, memfs):
    memfs.mkdir("/lake")
    common(
        "system",
        """
        def filesystems():
            return {"Lake": "memory:///lake", "Here": "."}
        """,
    )
    assert make()._filesystem_names == ["Lake", "Here"]
    # A path, fs or filesystems replaces them.
    assert make("memory:///lake")._filesystem_names == ["default"]
    assert make(filesystems={"Mine": memfs})._filesystem_names == ["Mine"]


def test_plugin_options_by_plugin(common):
    common(
        "system",
        """
        def plugin_options():
            return {"abfs-support": {"concurrency": 16, "priority": 1}}
        """,
    )
    explorer = make(".", plugin_options={"abfs-support": {"concurrency": 8}})
    [abfs] = [p for p in explorer._plugins if p.key == "abfs-support"]
    assert (abfs.options.concurrency, abfs.options.priority) == (8, 1)


def test_final_settings_ignored_with_a_warning(common, memfs):
    system = common(
        "system",
        """
        def parameters():
            return {"unsafe_mode": "blocked"}

        def filesystems():
            return {"Lake": "memory:///"}

        def final():
            return ["unsafe_mode", "filesystems"]
        """,
    )
    with pytest.warns(RuntimeWarning) as caught:
        explorer = make("/data", fs=memfs, unsafe_mode="always", height="300px")
    assert explorer._unsafe_policy == "blocked"
    assert explorer._filesystem_names == ["Lake"]
    assert explorer._height == "300px"
    assert [str(w.message) for w in caught] == [
        f"StorageExplorer's filesystems argument is ignored: it is final in {system}",
        f"StorageExplorer's unsafe_mode argument is ignored: it is final in {system}",
    ]
    # Pointing at the code creating the explorer: make()'s.
    assert {pathlib.Path(w.filename).name for w in caught} == {"explorers.py"}


def test_user_over_system_by_directory(common, user_common):
    common(
        "system",
        "def parameters():\n    return {'height': '500px', 'max_upload_bytes': 5}",
    )
    user_common("def parameters():\n    return {'height': '200px'}")
    explorer = make(".")
    assert explorer._height == "200px"
    assert explorer._incoming.max_bytes == 5


def test_disabled(common):
    common("system", "def parameters():\n    return {'height': '500px'}")
    assert make(".", common_config="disabled")._height == "400px"
    with pytest.raises(ValueError, match="common_config"):
        make(".", common_config="off")


def test_the_users_file_left_out_with_a_warning(user_common):
    path = user_common("def parameters():\n    return {'hieght': 1}")
    with pytest.warns(RuntimeWarning, match="Your common.py was left out") as caught:
        explorer = make(".")
    assert str(path) in str(caught[0].message)
    assert explorer._height == "400px"


def test_another_files_error_stops(common):
    path = common("system", "def parameters():\n    return {'hieght': 1}")
    with pytest.raises(ConfigError, match="unknown parameter 'hieght'") as info:
        make(".")
    assert str(info.value).startswith(str(path))
    assert isinstance(info.value, ValueError)


def test_a_value_refused_names_the_files(common):
    path = common("system", "def parameters():\n    return {'layout': 'wide'}")
    with pytest.raises(ValueError, match="layout") as info:
        make(".")
    assert info.value.__notes__ == [f"With the settings of {path}"]


def test_no_file_changes_nothing():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        explorer = make(".")
    assert explorer._height == "400px"
