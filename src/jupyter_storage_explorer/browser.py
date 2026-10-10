"""File browser widget: directory tree, file list, and a preview of the selected item."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import datetime as dt
import hashlib
import os
import pathlib
import re
import tempfile
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets
from fsspec.core import url_to_fs

from jupyter_storage_explorer.formats import (
    DEFAULT_FORMATS,
    DataFormat,
    MediaPreview,
    Preview,
    PreviewLimits,
    Recipe,
    Target,
    Text,
    UrlFor,
    default_url_for,
    matching_formats,
)
from jupyter_storage_explorer.formats import detect as detect_format
from jupyter_storage_explorer.formats.base import jsonable

if TYPE_CHECKING:
    from collections.abc import Callable

    from fsspec import AbstractFileSystem

_STATIC = pathlib.Path(__file__).parent / "static"
# JavaScript libraries the frontend may ask for (see static/vendor/README.md);
# only these names are served.
_VENDOR_FILES = frozenset({"marked.esm.js", "purify.es.mjs"})

# Keys used by different fsspec implementations for the modification time
# (local: mtime, s3fs: LastModified, adlfs: last_modified, gcsfs: updated).
_MTIME_KEYS = (
    "mtime",
    "LastModified",
    "last_modified",
    "updated",
    "modified",
    "created",
)

# Storage options whose names look like credentials are left out of generated
# snippets, since snippets get copied, shared and saved in notebooks.
_SECRET_OPTION = re.compile(
    r"key|secret|token|password|passwd|credential|sas|connection_string", re.IGNORECASE
)

# Largest file the text editor opens; the whole file is sent to the browser.
_MAX_EDIT_BYTES = 1024 * 1024
# Largest file that can be downloaded: it passes through kernel memory and the
# notebook's connection in one message.
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


def _open(
    path: str | None, fs: AbstractFileSystem | None, storage_options: Mapping[str, Any]
) -> tuple[AbstractFileSystem, str]:
    """A filesystem and the path to start at, from a URL/path or an existing filesystem."""
    if fs is None:
        fs, root = url_to_fs("." if path is None else path, **storage_options)
    elif storage_options:
        raise TypeError(
            "storage options cannot be combined with an existing filesystem"
        )
    else:
        root = fs._strip_protocol(fs.root_marker if path is None else path)
    # Top-level paths strip to "" on some backends (e.g. memory), which does
    # not match the "/..." names they list.
    return fs, root or fs.root_marker


def _parent(path: str, fs: AbstractFileSystem) -> str:
    """The directory containing ``path``, as the filesystem names it (e.g. "/" on memory://)."""
    path = _norm(path)
    if "/" not in path:
        return ""  # a top-level item of a filesystem whose top level is "" (e.g. DirFileSystem)
    parent = path.rsplit("/", 1)[0]
    return parent or fs.root_marker or "/"


def _is_dir(fs: AbstractFileSystem, path: str) -> bool:
    try:
        return fs.isdir(path)
    except Exception:
        return False


def _format_size(size: int) -> str:
    """E.g. "10 MB" or "1.5 GB", as shown to users."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:g} {unit}" if size == int(size) else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _safe_name(name: str) -> str:
    """A file name from the browser, without any directory part (so it cannot escape the target folder)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if name in ("", ".", ".."):
        raise ValueError(f"invalid file name: {name!r}")
    return name


def _version(data: bytes) -> str:
    """Identifies file contents, to detect changes made elsewhere while editing."""
    return hashlib.sha256(data).hexdigest()


def _norm(path: str) -> str:
    return path.rstrip("/") or path


def _basename(path: str) -> str:
    return _norm(path).rsplit("/", 1)[-1] or path


def _join(parent: str, name: str) -> str:
    return parent + name if not parent or parent.endswith("/") else f"{parent}/{name}"


def _to_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def _entry(info: dict[str, Any]) -> dict[str, Any]:
    is_dir = info.get("type") == "directory"
    mtime = next(
        (ts for key in _MTIME_KEYS if (ts := _to_timestamp(info.get(key))) is not None),
        None,
    )
    return {
        "name": _basename(info["name"]),
        "path": _norm(info["name"]),
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else info.get("size"),
        "mtime": mtime,
    }


def _is_plain(value: Any) -> bool:
    """Whether ``repr(value)`` is valid Python, so it can appear in generated code."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_plain(v) for v in value)
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _is_plain(v) for k, v in value.items())
    return False


def _snippet_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Storage options fit to put in generated code.

    Leaves out options that look like credentials, and ones whose values are
    objects rather than plain data (e.g. the filesystem a DirFileSystem wraps).
    """
    out: dict[str, Any] = {}
    for key, value in options.items():
        if _SECRET_OPTION.search(key):
            continue
        if isinstance(value, Mapping):
            # Filtered key by key, keeping e.g. client_kwargs' endpoint_url.
            out[key] = _snippet_options(value)
        elif _is_plain(value):
            out[key] = value
    return out


def _section(preview: Preview) -> dict[str, Any]:
    """A preview section as JSON for the frontend; media bytes are base64-encoded."""
    data = {f.name: getattr(preview, f.name) for f in dataclasses.fields(preview)}
    if isinstance(preview, MediaPreview) and preview.data is not None:
        data["data"] = base64.b64encode(preview.data).decode("ascii")
    return {"kind": preview.kind, **jsonable(data)}


class StorageExplorer(anywidget.AnyWidget):
    """Browse any fsspec-supported storage with a directory tree and a file list.

    Double-clicking a file (or the Preview button, or Preview in the
    right-click menu) opens a preview panel below the list. "Python code" in
    the right-click menu shows how to load it in the notebook, "Edit"
    opens text files in an editor that saves back to the storage, and
    "Download" saves the selected files (not folders) in the browser. Files
    dragged from JupyterLab's file browser or from the user's computer onto
    the list or tree are uploaded after a confirmation, and files dragged
    within the widget onto a folder are moved there (see ``_mv``).

    Examples:
        FileBrowser()                          # current local directory
        FileBrowser("s3://my-bucket/data", anon=True)
        FileBrowser("memory://")
        FileBrowser("data", fs=my_filesystem)  # an existing fsspec filesystem
        FileBrowser(filesystems={"Lake": s3, "Local": "file:///home/me/data"})

    Extra keyword arguments are passed to fsspec as storage options.
    When ``fs`` is given, ``path`` is a path within that filesystem instead.

    ``filesystems`` maps names to several filesystems, chosen with a
    drop-down in the widget (or by setting ``filesystem`` to a name); each
    remembers its current folder while another is shown. Values are fsspec
    filesystems (starting at their top level; wrap one in fsspec's
    ``DirFileSystem`` to start in a subfolder) or URLs (starting at that path).
    It cannot be combined with ``path``, ``fs`` or storage options.

    ``height`` is the height of the tree and file list; the preview panel adds
    to it. ``formats`` replaces the formats that can be previewed (default:
    ``DEFAULT_FORMATS``). ``max_upload_bytes`` limits the size of files
    uploaded from the user's computer (default 10 MB; None for no limit).

    ``url_for(fs, path)`` turns a path on the filesystem shown into the
    location used by "Copy URL", ``selected_urls``, "Python code" snippets
    and previews that read by location (e.g. with polars). The default,
    ``default_url_for``, gives a plain path for local files and
    ``protocol://path`` otherwise. Replace it to e.g. resolve a
    ``DirFileSystem`` to its underlying location; with several
    ``filesystems``, tell them apart by ``fs``.
    """

    _esm = _STATIC / "browser.js"
    _css = _STATIC / "browser.css"

    root = traitlets.Unicode().tag(sync=True)
    # Directory path -> list of {"name", "path"} of its subdirectories.
    # A directory that has not been listed yet has no key.
    tree = traitlets.Dict().tag(sync=True)
    current_dir = traitlets.Unicode().tag(sync=True)
    entries = traitlets.List().tag(sync=True)
    selected = traitlets.List(traitlets.Unicode()).tag(sync=True)
    error = traitlets.Unicode().tag(sync=True)
    # Height of the tree and file list (CSS). The preview panel adds its own
    # height below them, and both can be resized by dragging in the widget.
    height = traitlets.Unicode("400px").tag(sync=True)
    # Preview shown in the panel: {"path", "name", "format", "sections",
    # "error", "loading"}; empty when the panel is closed.
    preview = traitlets.Dict().tag(sync=True)
    # Format of the current directory itself (e.g. "Delta Lake table"), or ""
    # if it cannot be previewed; enables the Preview button when nothing is selected.
    current_format = traitlets.Unicode().tag(sync=True)
    # Format of the single selected item, for the Preview button's label:
    # {"path", "format"} ("format" is "" if it cannot be previewed); empty
    # unless exactly one item is selected. The path lets the frontend ignore
    # an answer for a previous selection.
    selected_format = traitlets.Dict().tag(sync=True)
    # Largest file that can be uploaded from the user's computer (bytes), or
    # None for no limit. Files dragged from JupyterLab's file browser are
    # copied by the kernel directly and are not limited.
    max_upload_bytes = traitlets.Int(10 * 1024 * 1024, allow_none=True).tag(sync=True)
    # Names of the filesystems to choose from, and the one shown. Setting
    # `filesystem` switches to it (the widget's drop-down does the same).
    filesystems = traitlets.List(traitlets.Unicode()).tag(sync=True)
    filesystem = traitlets.Unicode().tag(sync=True)

    def __init__(
        self,
        path: str | None = None,
        *,
        fs: AbstractFileSystem | None = None,
        filesystems: Mapping[str, AbstractFileSystem | str] | None = None,
        height: str = "400px",
        formats: Sequence[DataFormat] | None = None,
        preview_limits: PreviewLimits | None = None,
        max_upload_bytes: int | None = 10 * 1024 * 1024,
        url_for: UrlFor | None = None,
        **storage_options: Any,
    ) -> None:
        self._url_for: UrlFor = url_for or default_url_for
        self.formats = list(DEFAULT_FORMATS if formats is None else formats)
        self.preview_limits = preview_limits or PreviewLimits()
        # Uploads from the user's computer in progress: id -> {"file", "target", ...}.
        self._incoming: dict[str, dict[str, Any]] = {}
        # Name -> (filesystem, top-level path), and the folder each was left in.
        if filesystems is not None:
            if path is not None or fs is not None or storage_options:
                raise TypeError(
                    "filesystems cannot be combined with path, fs or storage options"
                )
            if not filesystems:
                raise ValueError("filesystems must not be empty")
            self._filesystems = {
                name: _open(value, None, {})
                if isinstance(value, str)
                else _open(None, value, {})
                for name, value in filesystems.items()
            }
        else:
            self._filesystems = {"default": _open(path, fs, storage_options)}
        self._remembered: dict[str, str] = {}
        name = next(iter(self._filesystems))
        self.fs: AbstractFileSystem = self._filesystems[name][0]
        super().__init__(
            height=height,
            max_upload_bytes=max_upload_bytes,
            filesystems=list(self._filesystems),
        )
        self.on_msg(self._on_custom_msg)
        self.filesystem = name  # shows its top level (see _on_filesystem)

    @traitlets.validate("filesystem")
    def _validate_filesystem(self, proposal: dict[str, Any]) -> str:
        if proposal["value"] not in self._filesystems:
            raise traitlets.TraitError(
                f"unknown filesystem {proposal['value']!r}; choose from {list(self._filesystems)}"
            )
        return proposal["value"]

    @traitlets.observe("filesystem")
    def _on_filesystem(self, change: dict[str, Any]) -> None:
        """Switch filesystems, remembering the folder left and returning to the one remembered."""
        if change["old"] in self._filesystems:
            self._remembered[change["old"]] = self.current_dir
        self.fs, root = self._filesystems[change["new"]]
        path = self._remembered.get(change["new"], root)
        if path != root and not _is_dir(self.fs, path):
            path = root  # the remembered folder is gone
        # One update for the frontend: separate ones would let it combine the
        # new root with the old folder (or the reverse) and ask the new
        # filesystem to list the old filesystem's paths.
        with self.hold_sync():
            self.preview = {}
            self.tree = {}
            self.root = root
            if self.current_dir == path:
                # Same path string as before (e.g. "/" on both), so no change event lists it.
                self._list(path)
            else:
                self.current_dir = path

    @property
    def selected_urls(self) -> list[str]:
        """Locations of the selected items (see ``url_for``), usable with ``fsspec.open``, pandas, etc."""
        return [self._url(p) for p in self.selected]

    def refresh(self) -> None:
        """Drop cached listings and reload the current directory."""
        self.fs.invalidate_cache()
        self.tree = {}
        self._list(self.current_dir)

    @traitlets.observe("current_dir")
    def _on_current_dir(self, change: dict[str, Any]) -> None:
        self._list(change["new"])

    @traitlets.observe("selected")
    def _on_selected(self, change: dict[str, Any]) -> None:
        if len(change["new"]) != 1:
            self.selected_format = {}
            return
        path = change["new"][0]
        try:
            _, formats = self._detect(path)
            name = formats[0].name if formats else ""
        except Exception:
            name = ""  # detection is best-effort; a failure just means no preview
        self.selected_format = {"path": path, "format": name}

    def _detect(self, path: str) -> tuple[Target, list[DataFormat]]:
        """The target at ``path`` and the formats matching it, best first."""
        info = self.fs.info(path)
        children = self._ls(path) if info.get("type") == "directory" else None
        target = Target(
            fs=self.fs, path=path, url=self._url(path), info=info, children=children
        )
        return target, matching_formats(target, self.formats)

    def open_preview(self, path: str, format: str | None = None) -> None:
        """Preview the file or directory at ``path`` in the preview panel.

        ``format`` names one of the formats matching it (e.g. "Text" for a JSON
        file); by default the best match is used.
        """
        base = {
            "path": path,
            "name": _basename(path),
            "format": None,
            "sections": [],
            "error": "",
        }
        # Shown while the (possibly remote) reads below run.
        self.preview = {**base, "loading": True}
        try:
            target, formats = self._detect(path)
            if format is not None:
                formats = [f for f in formats if f.name == format]
                if not formats:
                    raise ValueError(f"{path} cannot be previewed as {format}")
            if formats:
                base["format"] = formats[0].name
                base["sections"] = [
                    _section(s) for s in formats[0].preview(target, self.preview_limits)
                ]
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
        self.preview = base

    def close_preview(self) -> None:
        self.preview = {}

    def recipes(self, path: str) -> list[Recipe]:
        """Ways to load ``path`` in the notebook, from its best-matching format.

        Empty if its format is unknown. Storage options that look like
        credentials are left out of the code.
        """
        target, formats = self._detect(path)
        if not formats:
            return []
        return formats[0].recipes(target, _snippet_options(self.fs.storage_options))

    def _send_menu_info(self, path: str) -> None:
        """Answer the right-click menu's request: matching formats ("Preview as"),
        load code ("Python code") and whether it can be edited ("Edit")."""
        reply: dict[str, Any] = {"type": "menu_info", "path": path}
        try:
            target, formats = self._detect(path)
            reply["formats"] = [f.name for f in formats]
            options = _snippet_options(self.fs.storage_options)
            reply["recipes"] = (
                [dataclasses.asdict(r) for r in formats[0].recipes(target, options)]
                if formats
                else []
            )
            reply["editable"] = not target.is_dir and any(
                isinstance(f, Text) for f in formats
            )
        except Exception as exc:
            reply["error"] = f"{type(exc).__name__}: {exc}"
        self.send(reply)

    # --- Text editor ---

    def read_text(self, path: str) -> tuple[str, str]:
        """The text of a UTF-8 file, and a version string to pass to ``write_text``."""
        data = self.fs.cat_file(path)
        if len(data) > _MAX_EDIT_BYTES:
            raise ValueError(
                f"too large to edit (over {_MAX_EDIT_BYTES // (1024 * 1024)} MB)"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("not UTF-8 text") from None
        return text, _version(data)

    def write_text(self, path: str, text: str, version: str | None = None) -> str:
        """Save ``text`` to the file at ``path``; returns its new version.

        With ``version`` (from ``read_text``), refuses to save if the file has
        changed since, rather than overwriting that change. Files with Windows
        line endings keep them, although browsers edit text with "\\n" only.
        """
        current = self.fs.cat_file(path) if self.fs.exists(path) else b""
        if version is not None and _version(current) != version:
            raise RuntimeError(
                "the file has changed since it was opened; close the editor and open it again"
            )
        if b"\r\n" in current:
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        data = text.encode("utf-8")
        self.fs.pipe_file(path, data)
        self.fs.invalidate_cache(path)
        self._update_entry(path)
        if self.preview.get("path") == path:
            self.open_preview(path, self.preview.get("format"))
        return _version(data)

    def _update_entry(self, path: str) -> None:
        """Refresh the size and modification time shown for ``path`` in the list."""
        if any(e["path"] == path for e in self.entries):
            new = {**_entry(self.fs.info(path)), "url": self._url(path)}
            self.entries = [new if e["path"] == path else e for e in self.entries]

    def _edit_open(self, path: str) -> None:
        reply: dict[str, Any] = {"type": "edit_open", "path": path}
        try:
            reply["text"], reply["version"] = self.read_text(path)
        except Exception as exc:
            reply["error"] = f"Cannot open {_basename(path)}: {exc}"
        self.send(reply)

    def _edit_save(self, path: str, text: str, version: str | None) -> None:
        reply: dict[str, Any] = {"type": "edit_save", "path": path}
        try:
            reply["version"] = self.write_text(path, text, version)
        except Exception as exc:
            reply["error"] = f"Cannot save: {exc}"
        self.send(reply)

    # --- Download ---

    def _download(self, paths: list[str]) -> None:
        """Send each file to the browser, which saves it; one message per file."""
        for path in paths:
            reply: dict[str, Any] = {
                "type": "download",
                "path": path,
                "name": _basename(path),
            }
            try:
                info = self.fs.info(path)
                if info.get("type") == "directory":
                    raise ValueError("folders cannot be downloaded")
                size = info.get("size")
                if size is not None and size > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"too large to download (over {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB)"
                    )
                data = self.fs.cat_file(path)
            except Exception as exc:
                reply["error"] = f"{_basename(path)}: {exc}"
                self.send(reply)
            else:
                self.send(reply, [data])

    # --- Upload: copy files dragged in from JupyterLab's file browser ---

    def upload(
        self, sources: Sequence[str], dest: str, if_exists: str = "ask"
    ) -> dict[str, list[str]]:
        """Copy local files (paths on the kernel's machine) into directory ``dest``.

        ``if_exists`` decides what happens to files already in ``dest``: "ask"
        copies nothing and returns {"conflicts": [names]} if there are any;
        "overwrite" replaces them; "skip" leaves them. Otherwise returns
        {"copied": [...], "skipped": [...], "errors": [...]} (file names).
        Folders are not uploaded.
        """
        files, errors = [], []
        for source in sources:
            name = os.path.basename(source.rstrip("/\\"))
            if os.path.isdir(source):
                errors.append(f"{name}: folders are not uploaded")
            elif not os.path.isfile(source):
                # e.g. the kernel runs elsewhere than the Jupyter server (a remote kernel).
                errors.append(f"{name}: not found from the kernel")
            else:
                files.append((source, _join(dest, name)))
        existing = {target for _, target in files if self.fs.exists(target)}
        if if_exists == "ask" and existing:
            return {"conflicts": sorted(_basename(t) for t in existing)}
        copied, skipped = [], []
        for source, target in files:
            if target in existing and if_exists == "skip":
                skipped.append(_basename(target))
                continue
            try:
                self.fs.put_file(source, target)  # streams, so any size works
                copied.append(_basename(target))
            except Exception as exc:
                errors.append(f"{_basename(target)}: {exc}")
        if copied:
            self._refresh_dir(dest)
        return {"copied": copied, "skipped": skipped, "errors": errors}

    def _refresh_dir(self, path: str) -> None:
        """Show changes made to directory ``path`` in the list and tree."""
        self.fs.invalidate_cache(path)
        if path == self.current_dir:
            self._list(path)
        elif path in self.tree:
            self._load_children(path)

    def _upload(self, root: str, paths: list[str], dest: str, if_exists: str) -> None:
        """Answer a drop from JupyterLab's file browser: ``paths`` are relative to its server folder ``root``."""
        base = os.path.expanduser(root)
        sources = [os.path.join(base, *p.split("/")) for p in paths]
        reply: dict[str, Any] = {"type": "upload", "dest": dest}
        try:
            reply.update(self.upload(sources, dest, if_exists))
        except Exception as exc:
            reply["errors"] = [f"{type(exc).__name__}: {exc}"]
        self.send(reply)

    # --- Move: files dragged onto a folder in the list or tree ---

    def _mv(self, source: str, target: str) -> None:
        """Move one file to path ``target``, which does not exist (an existing
        file is removed first when overwriting).

        Override in a subclass to change how files are moved, e.g. to log
        moves, or to copy and delete on storage that cannot rename.
        """
        self.fs.mv(source, target)

    def move(
        self, paths: Sequence[str], dest: str, if_exists: str = "ask"
    ) -> dict[str, list[str]]:
        """Move files into directory ``dest`` on the filesystem shown, each with ``_mv``.

        ``if_exists`` decides what happens to files already in ``dest``: "ask"
        moves nothing and returns {"conflicts": [names]} if there are any;
        "overwrite" replaces them; "skip" leaves them (and the file to move).
        Otherwise returns {"moved": [...], "skipped": [...], "errors": [...]}
        (file names). Folders are not moved.
        """
        moves, errors = self._plan_moves(paths, dest)
        existing = {target for _, target in moves if self.fs.exists(target)}
        if if_exists == "ask" and existing:
            return {"conflicts": sorted(_basename(t) for t in existing)}
        moved, skipped = self._move_files(moves, existing, if_exists, errors)
        if moved:
            if self.preview.get("path") in moved:
                self.close_preview()
            for folder in {dest, *(_parent(p, self.fs) for p in moved)}:
                self._refresh_dir(folder)
        return {
            "moved": [_basename(p) for p in moved],
            "skipped": skipped,
            "errors": errors,
        }

    def _plan_moves(
        self, paths: Sequence[str], dest: str
    ) -> tuple[list[tuple[str, str]], list[str]]:
        """(source, target) pairs for the files to move, and errors for the rest."""
        moves, errors = [], []
        for path in paths:
            name = _basename(path)
            target = _join(dest, name)
            if _norm(path) == _norm(target):
                continue  # already in that folder
            if _is_dir(self.fs, path):
                errors.append(f"{name}: folders are not moved")
            else:
                moves.append((path, target))
        return moves, errors

    def _move_files(
        self,
        moves: list[tuple[str, str]],
        existing: set[str],
        if_exists: str,
        errors: list[str],
    ) -> tuple[list[str], list[str]]:
        """Move each (source, target) pair; returns the sources moved and the names
        skipped, and adds failures to ``errors``."""
        moved, skipped = [], []
        for source, target in moves:
            if target in existing and if_exists == "skip":
                skipped.append(_basename(target))
                continue
            try:
                if target in existing:
                    # Renaming onto an existing file fails on some systems.
                    self.fs.rm(target)
                self._mv(source, target)
                moved.append(source)
            except Exception as exc:
                errors.append(f"{_basename(source)}: {exc}")
        return moved, skipped

    # --- Upload from the user's computer: the browser sends files in pieces ---

    def _upload_check(self, dest: str, names: list[str]) -> dict[str, Any]:
        """Which of ``names`` already exist in ``dest``."""
        return {
            "conflicts": [
                n for n in names if self.fs.exists(_join(dest, _safe_name(n)))
            ]
        }

    def _upload_chunk(
        self, content: dict[str, Any], buffers: list[Any]
    ) -> dict[str, Any]:
        """Append one piece of a file; on the last piece, copy the whole file to the storage.

        Pieces go to a local temporary file first, so a failed or abandoned
        upload never leaves a partial file in the storage.
        """
        upload_id = content["id"]
        try:
            state = self._incoming.get(upload_id)
            if state is None:
                target = _join(content["dest"], _safe_name(content["name"]))
                handle, temp_path = tempfile.mkstemp(prefix="jse-upload-")
                # Opened per piece below, so none stays open between messages.
                os.close(handle)
                # The filesystem is kept, as the user may switch to another meanwhile.
                state = {"path": temp_path, "target": target, "size": 0, "fs": self.fs}
                self._incoming[upload_id] = state
            if buffers:
                piece = bytes(buffers[0])
                state["size"] += len(piece)
                # The frontend checks too; this guards against a file larger than it said.
                limit = self.max_upload_bytes
                if limit is not None and state["size"] > limit:
                    raise ValueError(
                        f"too large to upload (over {_format_size(limit)})"
                    )
                with open(state["path"], "ab") as f:
                    f.write(piece)
            if not content["last"]:
                return {}
            state["fs"].put_file(state["path"], state["target"])
            result: dict[str, Any] = {"done": True}
        except Exception as exc:
            # The frontend stops sending this file after an error.
            result = {"error": f"{_basename(content['name'])}: {exc}"}
        self._discard_upload(upload_id)
        return result

    def _discard_upload(self, upload_id: str) -> None:
        state = self._incoming.pop(upload_id, None)
        if state is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(state["path"])

    def _reply(self, content: dict[str, Any], result: dict[str, Any]) -> None:
        """Answer a request the frontend waits for, matched by its "rid"."""
        self.send({"type": "reply", "rid": content["rid"], **result})

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], buffers: Any
    ) -> None:
        """Handle a message from the frontend, by its "type"."""
        handler = self._message_handlers().get(content.get("type"))
        if handler is not None:
            handler(content, buffers or [])

    def _message_handlers(
        self,
    ) -> dict[str, Callable[[dict[str, Any], list[Any]], None]]:
        """Message type -> handler(content, buffers). Requests the frontend waits
        for (those with a "rid") are answered with ``_reply``."""
        return {
            "expand": lambda c, _: self._load_children(c["path"]),
            "refresh": lambda c, _: self.refresh(),
            "preview": lambda c, _: self.open_preview(c["path"], c.get("format")),
            "menu_info": lambda c, _: self._send_menu_info(c["path"]),
            "edit_open": lambda c, _: self._edit_open(c["path"]),
            "edit_save": lambda c, _: self._edit_save(
                c["path"], c["text"], c.get("version")
            ),
            "download": lambda c, _: self._download(c["paths"]),
            "upload": lambda c, _: self._upload(
                c["root"], c["paths"], c["dest"], c.get("if_exists", "ask")
            ),
            "upload_check": lambda c, _: self._reply(
                c, self._upload_check(c["dest"], c["names"])
            ),
            "upload_chunk": lambda c, b: self._reply(c, self._upload_chunk(c, b)),
            "upload_done": lambda c, _: self._reply(c, self._upload_done(c["dest"])),
            "vendor": lambda c, _: self._reply(c, self._vendor_source(c["name"])),
            "move": lambda c, _: self._reply(c, self._move_request(c)),
        }

    def _upload_done(self, dest: str) -> dict[str, Any]:
        self._refresh_dir(dest)
        return {}

    def _vendor_source(self, name: str) -> dict[str, Any]:
        """Source of a bundled library, e.g. marked for Markdown previews."""
        if name not in _VENDOR_FILES:
            return {"error": f"unknown library {name!r}"}
        return {"source": (_STATIC / "vendor" / name).read_text(encoding="utf-8")}

    def _move_request(self, content: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.move(
                content["paths"], content["dest"], content.get("if_exists", "ask")
            )
        except Exception as exc:
            return {"errors": [f"{type(exc).__name__}: {exc}"]}

    def _ancestors(self, path: str) -> list[str]:
        """Directories from the root down to (but excluding) ``path``."""
        if not path.startswith(self.root):
            return []
        out, cur = [], self.root
        for segment in filter(None, path[len(self.root) :].split("/")):
            out.append(cur)
            cur = _join(cur, segment)
        return out

    def _ls(self, path: str) -> list[dict[str, Any]]:
        infos = self.fs.ls(path, detail=True)
        # Some backends include the directory itself in its own listing.
        return [i for i in infos if _norm(i["name"]) != _norm(path)]

    def _load_children(self, path: str) -> None:
        try:
            infos = self._ls(path)
        except Exception as exc:
            self.error = f"Cannot list {path}: {exc}"
            infos = []
        self._set_children(path, infos)

    def _url(self, path: str) -> str:
        """Location of ``path`` on the filesystem shown, from ``url_for``.

        The one place paths become locations: "Copy URL", ``selected_urls``,
        "Python code" snippets and previews that read by location all use it.
        """
        return self._url_for(self.fs, path)

    def _set_children(self, path: str, infos: list[dict[str, Any]]) -> None:
        dirs = sorted(
            (
                {
                    "name": _basename(i["name"]),
                    "path": _norm(i["name"]),
                    "url": self._url(_norm(i["name"])),
                }
                for i in infos
                if i.get("type") == "directory"
            ),
            key=lambda d: d["name"].lower(),
        )
        self.tree = {**self.tree, path: dirs}

    def _list(self, path: str) -> None:
        # Make sure the tree can be expanded down to the current directory.
        for ancestor in self._ancestors(path):
            if ancestor not in self.tree:
                self._load_children(ancestor)
        try:
            infos = self._ls(path)
        except Exception as exc:
            self.error = f"Cannot list {path}: {exc}"
            self.entries = []
            self.selected = []
            self.current_format = ""
            return
        self.error = ""
        self._set_children(path, infos)
        self.entries = [
            {**(e := _entry(i)), "url": self._url(e["path"])} for i in infos
        ]
        self.selected = []
        self.current_format = self._directory_format(path, infos)

    def _directory_format(self, path: str, infos: list[dict[str, Any]]) -> str:
        """Name of the format of directory ``path`` given its listing, or "" if none."""
        # The listing is all directory formats need, so skip fetching the
        # directory's own info.
        target = Target(
            fs=self.fs,
            path=path,
            url=self._url(path),
            info={"name": path, "type": "directory"},
            children=infos,
        )
        try:
            fmt = detect_format(target, self.formats)
        except Exception:
            return ""  # detection is best-effort; a failure just means no preview
        return fmt.name if fmt is not None else ""
