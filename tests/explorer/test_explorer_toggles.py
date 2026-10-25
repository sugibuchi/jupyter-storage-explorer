"""StorageExplorer's toggles: unsafe_mode, whether folder operations are
offered on demand, always or never; code_snippet, which engines' code
"Python code" shows."""

from __future__ import annotations

import pytest
from all_actions import installed_only
from explorers import make, path_of


def delete_folder(explorer, *, unsafe):
    """Delete /data/table as the frontend asks, its switch on or off."""
    return explorer.request(
        {"type": "delete", "rid": 1, "paths": ["/data/table"], "unsafe": unsafe}
    )


@pytest.fixture
def lake(memfs):
    memfs.pipe_file("/data/a.csv", b"x,y\n1,2\n")
    memfs.pipe_file("/data/b.json", b"{}")
    memfs.pipe_file("/data/table/part.txt", b"x")
    return memfs


class TestUnsafeMode:
    def test_on_demand_by_default(self, lake):
        explorer = make("/", fs=lake)
        assert explorer._unsafe_policy == "on_demand"
        assert delete_folder(explorer, unsafe=False)["deleted"] == []
        assert delete_folder(explorer, unsafe=True)["deleted"] == ["table"]

    def test_always(self, lake):
        explorer = make("/", fs=lake, unsafe_mode="always")
        assert explorer._unsafe_policy == "always"
        assert delete_folder(explorer, unsafe=False)["deleted"] == ["table"]

    def test_blocked_whatever_the_page_sends(self, lake):
        explorer = make("/", fs=lake, unsafe_mode="blocked")
        explorer._unsafe_policy = "always"  # as a page could set it
        explorer._unsafe_mode = True
        reply = delete_folder(explorer, unsafe=True)
        assert reply["deleted"] == []
        assert "folders are not deleted" in reply["errors"][0]
        assert lake.exists("/data/table/part.txt")

    def test_files_whatever_the_mode(self, lake):
        explorer = make("/", fs=lake, unsafe_mode="blocked")
        reply = explorer.request({"type": "delete", "rid": 1, "paths": ["/data/a.csv"]})
        assert reply["deleted"] == ["a.csv"]

    def test_unknown_value(self, lake):
        with pytest.raises(ValueError, match="unsafe_mode must be one of"):
            make("/", fs=lake, unsafe_mode="sometimes")


class TestCodeSnippet:
    @pytest.fixture
    def folder(self, tmp_path):
        """Local files: polars gives no code for the memory filesystem."""
        (tmp_path / "a.csv").write_bytes(b"x,y\n1,2\n")
        (tmp_path / "b.json").write_bytes(b"{}")
        return str(tmp_path)

    @staticmethod
    def engines(explorer, name="a.csv"):
        path = path_of(explorer, name)
        reply = explorer.request({"type": "menu_info", "rid": 1, "path": path})
        return sorted({recipe["engine"] for recipe in reply["recipes"]})

    def test_every_engine_installed_by_default(self, folder, monkeypatch):
        explorer = make(folder)
        assert explorer._code_snippet
        installed_only(monkeypatch, "polars", "pandas", "pyspark", "pyarrow")
        assert self.engines(explorer) == ["Polars", "PySpark", "pandas"]
        installed_only(monkeypatch, "polars", "databricks-connect")
        # Not Databricks Connect: its cluster cannot read the kernel's files.
        assert self.engines(explorer) == ["Polars"]
        anywhere = {"databricks-connect": {"*": {"supported_protocols": None}}}
        explorer = make(folder, engine_options=anywhere)
        assert self.engines(explorer) == ["Databricks Connect", "Polars"]

    def test_disabled(self, folder):
        explorer = make(folder, code_snippet="disabled")
        assert not explorer._code_snippet
        assert self.engines(explorer) == []

    def test_engines_named(self, folder):
        explorer = make(folder, code_snippet=["polars", "python"])
        assert explorer._code_snippet
        assert self.engines(explorer) == ["Polars"]
        # "python": the code of the formats without an engine, e.g. JSON.
        assert "Python" in self.engines(explorer, "b.json")

    def test_unknown_engines_left_out_with_a_warning(self, folder):
        with pytest.warns(RuntimeWarning, match="no action of vaex"):
            explorer = make(folder, code_snippet=["vaex", "pandas"])
        assert self.engines(explorer) == ["pandas"]

    @pytest.mark.parametrize("value", ["polars", "yes", [1]])
    def test_neither_a_choice_nor_a_list_of_keys(self, lake, value):
        with pytest.raises(ValueError, match="code_snippet must be"):
            make("/", fs=lake, code_snippet=value)
