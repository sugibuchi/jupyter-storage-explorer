"""StorageExplorer's files opened in JupyterLab."""

from __future__ import annotations

import contextlib
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

    def test_notebook_cells_are_untrusted(self, mem_explorer, memfs):
        """Whatever a notebook's cells claim: JupyterLab would run their HTML
        and JavaScript outputs (the Jupyter server checks a signature)."""
        cells = [
            {
                "cell_type": "code",
                "metadata": {"trusted": True, "tags": ["x"]},
                "source": "1",
                "outputs": [],
            },
            {"cell_type": "markdown", "source": "no metadata"},
        ]
        notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": cells}
        memfs.pipe_file("/data/n.ipynb", json.dumps(notebook).encode())
        model = self.get(mem_explorer, "/data/n.ipynb", contentType="notebook")["model"]
        metadata = [cell["metadata"] for cell in model["content"]["cells"]]
        assert metadata == [{"trusted": False, "tags": ["x"]}, {"trusted": False}]
        # A text editor opening it gets the file as it is.
        text = self.get(
            mem_explorer, "/data/n.ipynb", contentType="file", format="text"
        )["model"]
        assert '"trusted": true' in text["content"]
        # Saved without it, as nbformat writes notebooks.
        self.save(mem_explorer, "/data/n.ipynb", model["content"], format="json")
        saved = json.loads(memfs.cat_file("/data/n.ipynb"))
        assert [cell["metadata"] for cell in saved["cells"]] == [{"tags": ["x"]}, {}]

    def notebook(self, *, trusted: bool) -> dict[str, Any]:
        """A notebook as JupyterLab saves it: a code cell with rich output,
        trusted or not, and a Markdown cell."""
        output = {
            "output_type": "display_data",
            "metadata": {},
            "data": {"text/html": "<b>chart</b>", "text/plain": "chart"},
        }
        code = {
            "cell_type": "code",
            "execution_count": 1,
            "id": "c1",
            "metadata": {"trusted": trusted},
            "source": "1",
            "outputs": [output],
        }
        text = {"cell_type": "markdown", "id": "m1", "metadata": {}, "source": "# x"}
        return {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [code, text],
        }

    def trust(self, explorer: Explorer, path: str) -> list[Any]:
        model = self.get(explorer, path, contentType="notebook")["model"]
        return [cell["metadata"].get("trusted") for cell in model["content"]["cells"]]

    def test_saved_trusted_is_trusted_when_opened_again(self, mem_explorer, memfs):
        """As in JupyterLab: saving a trusted notebook signs it (nbformat's
        notary); its code cells are trusted when opened again."""
        memfs.pipe_file("/data/n.ipynb", b"{}")
        notebook = self.notebook(trusted=True)
        self.save(mem_explorer, "/data/n.ipynb", notebook, format="json")
        assert "trusted" not in memfs.cat_file("/data/n.ipynb").decode()
        assert self.trust(mem_explorer, "/data/n.ipynb") == [True, False]

    def test_saved_untrusted_is_not_signed(self, mem_explorer, memfs):
        memfs.pipe_file("/data/n.ipynb", b"{}")
        self.save(
            mem_explorer, "/data/n.ipynb", self.notebook(trusted=False), format="json"
        )
        assert self.trust(mem_explorer, "/data/n.ipynb") == [False, False]

    def test_changed_elsewhere_is_untrusted(self, mem_explorer, memfs):
        """Any change to a signed notebook (here its output) voids its signature."""
        memfs.pipe_file("/data/n.ipynb", b"{}")
        self.save(
            mem_explorer, "/data/n.ipynb", self.notebook(trusted=True), format="json"
        )
        text = memfs.cat_file("/data/n.ipynb").decode().replace("chart", "evil")
        memfs.pipe_file("/data/n.ipynb", text.encode())
        assert self.trust(mem_explorer, "/data/n.ipynb") == [False, False]

    def test_another_users_signature_does_not_count(
        self, mem_explorer, memfs, monkeypatch, tmp_path
    ):
        """Signatures are the user's (their secret and database)."""
        memfs.pipe_file("/data/n.ipynb", b"{}")
        self.save(
            mem_explorer, "/data/n.ipynb", self.notebook(trusted=True), format="json"
        )
        monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path / "another-user"))
        assert self.trust(mem_explorer, "/data/n.ipynb") == [False, False]

    def test_without_the_notary_untrusted(self, mem_explorer, memfs, monkeypatch):
        """Without nbformat (or if its notary cannot be used): never trusted."""

        @contextlib.contextmanager
        def no_notary():
            yield None

        memfs.pipe_file("/data/n.ipynb", b"{}")
        self.save(
            mem_explorer, "/data/n.ipynb", self.notebook(trusted=True), format="json"
        )
        monkeypatch.setattr(jupyterlab_files, "_notary", no_notary)
        assert self.trust(mem_explorer, "/data/n.ipynb") == [False, False]
