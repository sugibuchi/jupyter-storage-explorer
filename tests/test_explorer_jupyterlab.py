"""StorageExplorer's files opened in JupyterLab."""

from __future__ import annotations

import json
from typing import Any

from explorers import Explorer, entries, make

from jupyter_storage_explorer._explorer import jupyterlab_files


class TestOpenInJupyterLab:
    """The requests of the launcher's drive ("Open in JupyterLab"), through the explorer."""

    def get(self, explorer: Explorer, path: str, **options: Any) -> dict[str, Any]:
        return explorer.request(
            {
                "type": "jupyterlab_get",
                "rid": 1,
                "filesystem": explorer._filesystem,
                "path": path,
                **options,
            }
        )

    def save(self, explorer: Explorer, path: str, content: Any, **options: Any):
        return explorer.request(
            {
                "type": "jupyterlab_save",
                "rid": 2,
                "filesystem": explorer._filesystem,
                "path": path,
                "content": content,
                "format": "text",
                **options,
            }
        )

    def test_get_and_save(self, mem_explorer, memfs):
        model = self.get(mem_explorer, "/data/notes.md", format="text")["model"]
        assert model["content"] == "# Notes\n"
        saved = self.save(mem_explorer, "/data/notes.md", "# Changed\n")["model"]
        assert memfs.cat_file("/data/notes.md") == b"# Changed\n"
        assert saved["content"] is None and saved["hash"] != model["hash"]
        # The list shows the new size.
        mem_explorer._current_dir = "/data"
        assert {e["name"]: e["size"] for e in entries(mem_explorer)}["notes.md"] == 10

    def test_by_storage_name_while_another_is_shown(self, memfs):
        memfs.pipe_file("/a/f.txt", b"a")
        memfs.pipe_file("/b/g.txt", b"b")
        explorer = make(filesystems={"A": "memory:///a", "B": "memory:///b"})
        explorer._filesystem = "B"
        reply = explorer.request(
            {
                "type": "jupyterlab_save",
                "rid": 1,
                "filesystem": "A",
                "path": "/a/f.txt",
                "content": "new",
                "format": "text",
            }
        )
        assert "model" in reply
        assert memfs.cat_file("/a/f.txt") == b"new"

    def test_preview_of_the_file_follows(self, mem_explorer):
        mem_explorer._open_preview("/data/notes.md", "markdown")
        self.save(mem_explorer, "/data/notes.md", "# Changed\n")
        assert "Changed" in json.dumps(mem_explorer._preview)

    def test_refused(self, mem_explorer):
        assert "error" in self.get(mem_explorer, "/data")  # a folder
        assert "error" in self.get(mem_explorer, "/data/missing.txt")
        assert "error" in self.get(mem_explorer, "/data/../other/b.txt")
        other = mem_explorer.request(
            {
                "type": "jupyterlab_get",
                "rid": 1,
                "filesystem": "nope",
                "path": "/data/a.csv",
            }
        )
        assert other["error"] == "not a file of this explorer's storages"

    def test_text_formats(self, mem_explorer):
        # Opened in JupyterLab's text editor even when it does not know the
        # file type; data files are not (Parquet, Excel), nor are formats
        # JupyterLab knows itself (CSV, JSON).
        assert {"text", "markdown"} <= set(mem_explorer._text_formats)
        assert not {"parquet", "excel", "delta", "image", "csv"} & set(
            mem_explorer._text_formats
        )

    def test_too_large(self, mem_explorer, memfs, monkeypatch):
        monkeypatch.setattr(jupyterlab_files, "MAX_BYTES", 3)
        assert "too large" in self.get(mem_explorer, "/data/a.csv")["error"]
