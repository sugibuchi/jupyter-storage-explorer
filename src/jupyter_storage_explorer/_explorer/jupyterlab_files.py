"""Files opened in JupyterLab's own editors and viewers ("Open in JupyterLab").

The launcher's JupyterLab extension serves them through a drive of its own
(launcher/labextension/src/files.ts), which asks the explorer's kernel for a
file's contents and to save them. These functions turn a file's bytes into
the contents model JupyterLab expects (as its server's contents API returns
it) and the content it saves back into bytes.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import json
import mimetypes
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _infos, _paths

if TYPE_CHECKING:
    from collections.abc import Iterator

# Largest file opened in JupyterLab: it passes through kernel memory and the
# notebook's connection in one message, and an editor holds all of it.
MAX_BYTES = 20 * 1024 * 1024


def _iso(timestamp: float | None) -> str:
    """A time as the contents API gives it; now when the storage does not say."""
    moment = (
        dt.datetime.now(dt.UTC)
        if timestamp is None
        else dt.datetime.fromtimestamp(timestamp, dt.UTC)
    )
    return moment.isoformat().replace("+00:00", "Z")


def _is_notebook(name: str, type_: str | None, format_: str | None) -> bool:
    """Whether JupyterLab asks for the file as a notebook: its notebook view
    does (type "notebook"); a text editor opening an .ipynb file does not."""
    if type_ is not None:
        return type_ == "notebook"
    return name.endswith(".ipynb") and format_ in (None, "json")


def contents_model(
    path: str,
    data: bytes,
    info: dict[str, Any],
    *,
    type_: str | None = None,
    format_: str | None = None,
    content: bool = True,
    writable: bool = True,
) -> dict[str, Any]:
    """The contents model of the file at ``path``, ``data`` its bytes and
    ``info`` its fsspec info, as JupyterLab asked for it: ``type_`` ("file",
    "notebook" or None), ``format_`` ("text", "base64", "json" or None: as
    the file allows) and with ``content`` or without. ``writable`` False
    tells JupyterLab the file is only read.

    The hash lets JupyterLab tell, before saving, whether the file has been
    changed elsewhere since it was opened (it then asks what to do).
    Raises ValueError for content that cannot be given in the format asked.
    """
    name = _paths.basename(path)
    notebook = _is_notebook(name, type_, format_)
    modified = _iso(_infos.mtime(info))
    created = _infos.ctime(info)
    model: dict[str, Any] = {
        "name": name,
        "path": path,
        "type": "notebook" if notebook else "file",
        "writable": writable,
        "created": modified if created is None else _iso(created),
        "last_modified": modified,
        "size": len(data),
        "mimetype": None if notebook else mimetypes.guess_type(name)[0],
        "content": None,
        "format": None,
        "hash": hashlib.sha256(data).hexdigest(),
        "hash_algorithm": "sha256",
    }
    if not content:
        return model
    if notebook or format_ == "json":
        try:
            model["content"] = json.loads(data.decode("utf-8"))
        except ValueError:
            raise ValueError(f"{name} is not a valid notebook (JSON)") from None
        model["format"] = "json"
        if notebook:
            model["content"] = _trusted_as_signed(model["content"])
    elif format_ == "base64":
        model["content"] = base64.b64encode(data).decode("ascii")
        model["format"] = "base64"
    else:
        try:
            model["content"] = data.decode("utf-8")
            model["format"] = "text"
        except UnicodeDecodeError:
            if format_ == "text":
                raise ValueError(f"{name} is not UTF-8 text") from None
            model["content"] = base64.b64encode(data).decode("ascii")
            model["format"] = "base64"
    if model["mimetype"] is None and model["format"] == "text":
        model["mimetype"] = "text/plain"
    return model


def _trusted_as_signed(notebook: Any) -> Any:
    """``notebook`` with its cells marked trusted as the Jupyter server marks
    them: its code cells if the notary knows its signature (it was saved
    trusted by this user), else none, whatever the file says.

    JupyterLab runs a cell's HTML and JavaScript outputs, unsanitized, only if
    the cell's metadata says it is trusted: a notebook from a storage, which
    anyone with write access may have crafted, never runs anything by itself.
    The user can still trust it (JupyterLab's "Trust Notebook"), and saving it
    then signs it (see ``saved_bytes``).
    """
    marked = _untrusted(notebook)
    with _notary() as notary:
        if notary is not None and _is_signed(notary, notebook):
            for cell in marked["cells"]:
                if isinstance(cell, dict) and cell.get("cell_type") == "code":
                    cell["metadata"]["trusted"] = True
    return marked


@contextlib.contextmanager
def _notary() -> Iterator[Any]:
    """nbformat's notary with its defaults (the user's secret and database
    of signatures, as the Jupyter server's unless configured otherwise), or
    None without nbformat or if it cannot be used: notebooks are then
    untrusted, and nothing is signed."""
    try:
        from nbformat.sign import NotebookNotary  # noqa: PLC0415 (optional)

        notary = NotebookNotary()
        notary.__enter__()
    except Exception:
        yield None
        return
    try:
        yield notary
    finally:
        notary.__exit__(None, None, None)


def _is_signed(notary: Any, notebook: Any) -> bool:
    """Whether the notary knows ``notebook``'s signature (as read from the file)."""
    try:
        import nbformat  # noqa: PLC0415 (optional)

        return bool(notary.check_signature(nbformat.from_dict(notebook)))
    except Exception:
        return False


def _untrusted(notebook: Any) -> Any:
    """``notebook`` with every cell marked untrusted, whatever the file says."""
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        return notebook

    def untrusted(cell: Any) -> Any:
        if not isinstance(cell, dict):
            return cell
        metadata = cell.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return {**cell, "metadata": {**metadata, "trusted": False}}

    return {**notebook, "cells": [untrusted(cell) for cell in notebook["cells"]]}


def _strip_transient(notebook: dict[str, Any]) -> dict[str, Any]:
    """A notebook without what JupyterLab adds while it is open and nbformat
    removes before writing (as its ``strip_transient``): whether each cell is
    trusted, and the notebook's original format version."""

    def without(mapping: Any, keys: tuple[str, ...]) -> Any:
        if not isinstance(mapping, dict):
            return mapping
        return {k: v for k, v in mapping.items() if k not in keys}

    notebook = dict(notebook)
    if "metadata" in notebook:
        notebook["metadata"] = without(
            notebook["metadata"], ("orig_nbformat", "orig_nbformat_minor", "signature")
        )
    if isinstance(notebook.get("cells"), list):
        notebook["cells"] = [
            {**cell, "metadata": without(cell["metadata"], ("trusted",))}
            if isinstance(cell, dict) and "metadata" in cell
            else cell
            for cell in notebook["cells"]
        ]
    return notebook


def _all_code_cells_trusted(notebook: dict[str, Any]) -> bool:
    """Whether every code cell of ``notebook`` (as JupyterLab saves it) is
    trusted, as the notary checks before signing (``check_cells``)."""
    with _notary() as notary:
        if notary is None:
            return False
        try:
            import nbformat  # noqa: PLC0415 (optional)

            return bool(notary.check_cells(nbformat.from_dict(notebook)))
        except Exception:
            return False


def _sign(notebook: dict[str, Any]) -> None:
    """Record ``notebook``'s signature (as written) with the notary, so that it
    is trusted when opened again, here or by the Jupyter server."""
    with _notary() as notary:
        if notary is None:
            return
        with contextlib.suppress(Exception):
            import nbformat  # noqa: PLC0415 (optional)

            notary.sign(nbformat.from_dict(notebook))


def saved_bytes(content: Any, format_: str | None, current: bytes | None) -> bytes:
    """The bytes to write for ``content`` saved by JupyterLab in ``format_``.

    ``current``: the file's bytes before, if it exists. Notebooks are written
    as nbformat writes them; text files with Windows line endings keep them,
    although browsers edit text with "\\n" only.
    """
    if format_ == "json":
        if isinstance(content, dict):
            trusted = _all_code_cells_trusted(content)
            content = _strip_transient(content)
            if trusted:
                _sign(content)
        return (
            json.dumps(content, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    if format_ == "base64":
        return base64.b64decode(content)
    if format_ != "text" or not isinstance(content, str):
        raise ValueError(f"cannot save content in format {format_!r}")
    if current is not None and b"\r\n" in current:
        content = content.replace("\r\n", "\n").replace("\n", "\r\n")
    return content.encode("utf-8")
