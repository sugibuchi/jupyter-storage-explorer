"""Files opened in JupyterLab's editors: contents models and saved bytes (_jupyterlab_files.py)."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from jupyter_storage_explorer._jupyterlab_files import contents_model, saved_bytes

INFO = {"name": "d/f", "type": "file", "size": 5, "mtime": 1_700_000_000.0}


class TestContentsModel:
    def test_text_file(self):
        model = contents_model("d/notes.txt", b"hello", INFO)
        assert model["name"] == "notes.txt"
        assert model["path"] == "d/notes.txt"
        assert (model["type"], model["format"], model["content"]) == (
            "file",
            "text",
            "hello",
        )
        assert model["mimetype"] == "text/plain"
        assert model["last_modified"] == "2023-11-14T22:13:20Z"
        assert model["created"] == model["last_modified"]  # not in INFO
        assert model["hash"] == hashlib.sha256(b"hello").hexdigest()
        assert model["hash_algorithm"] == "sha256"
        assert model["writable"] is True

    def test_without_content_still_has_the_hash(self):
        # JupyterLab compares it before saving, to detect changes made elsewhere.
        model = contents_model("d/notes.txt", b"hello", INFO, content=False)
        assert model["content"] is None and model["format"] is None
        assert model["hash"] == hashlib.sha256(b"hello").hexdigest()

    def test_binary_as_base64(self):
        data = b"\x89PNG\x00\xff"
        model = contents_model("d/a.png", data, INFO, format_="base64")
        assert model["format"] == "base64"
        assert base64.b64decode(model["content"]) == data
        assert model["mimetype"] == "image/png"
        # Without a format asked: base64 when it is not UTF-8 text.
        assert contents_model("d/a.png", data, INFO)["format"] == "base64"

    def test_text_asked_of_binary_refused(self):
        with pytest.raises(ValueError, match="not UTF-8 text"):
            contents_model("d/a.bin", b"\xff\xfe", INFO, format_="text")

    def test_notebook(self):
        nb = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        data = json.dumps(nb).encode()
        model = contents_model(
            "d/a.ipynb", data, INFO, type_="notebook", format_="json"
        )
        assert (model["type"], model["format"], model["content"]) == (
            "notebook",
            "json",
            nb,
        )
        # Opened in the text editor ("Open With"), it is text.
        model = contents_model("d/a.ipynb", data, INFO, type_="file", format_="text")
        assert (model["type"], model["format"]) == ("file", "text")

    def test_invalid_notebook_refused(self):
        with pytest.raises(ValueError, match="not a valid notebook"):
            contents_model("d/a.ipynb", b"{", INFO, type_="notebook", format_="json")

    def test_creation_time(self):
        model = contents_model("d/f.txt", b"", {**INFO, "created": 1_600_000_000.0})
        assert model["created"] == "2020-09-13T12:26:40Z"


class TestSavedBytes:
    def test_text(self):
        assert saved_bytes("a\nb", "text", None) == b"a\nb"

    def test_windows_line_endings_kept(self):
        assert saved_bytes("a\nb\n", "text", b"x\r\ny") == b"a\r\nb\r\n"

    def test_base64(self):
        assert (
            saved_bytes(base64.b64encode(b"\x00\xff").decode(), "base64", None)
            == b"\x00\xff"
        )

    def test_notebook_as_nbformat_writes_it(self):
        data = saved_bytes({"b": 1, "a": "é"}, "json", None)
        assert data == '{\n "a": "é",\n "b": 1\n}\n'.encode()

    def test_notebook_without_what_jupyterlab_adds(self):
        nb = {
            "cells": [
                {"cell_type": "code", "metadata": {"trusted": True, "tags": ["x"]}}
            ],
            "metadata": {"orig_nbformat": 4, "kernelspec": {"name": "python3"}},
        }
        written = json.loads(saved_bytes(nb, "json", None))
        assert written["cells"][0]["metadata"] == {"tags": ["x"]}
        assert written["metadata"] == {"kernelspec": {"name": "python3"}}

    def test_unknown_format_refused(self):
        with pytest.raises(ValueError, match="cannot save"):
            saved_bytes("x", None, None)
