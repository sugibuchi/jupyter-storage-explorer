"""Storage explorer widget: directory tree, file list, and a preview of the selected item."""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import functools
import hashlib
import os
import uuid
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets
from fsspec.core import url_to_fs

from jupyter_storage_explorer import _paths, _static
from jupyter_storage_explorer._urls import default_url
from jupyter_storage_explorer.file_tasks import FileTasks, Plan, Task
from jupyter_storage_explorer.formats import (
    DataFormat,
    MediaPreview,
    Preview,
    PreviewLimits,
    Recipe,
    Target,
    Text,
    explorer_formats,
    matching_formats,
)
from jupyter_storage_explorer.formats import detect as detect_format
from jupyter_storage_explorer.formats.base import jsonable
from jupyter_storage_explorer.incoming import IncomingFiles
from jupyter_storage_explorer.jobs import JobRunner
from jupyter_storage_explorer.listing import Listing
from jupyter_storage_explorer.operations import (
    AsyncFsspecOperations,
    FsspecOperations,
    OperationChain,
    Progress,
)
from jupyter_storage_explorer.query import DataQuery, QuerySettingsStore
from jupyter_storage_explorer.query import default_store as default_query_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.jobs import Job
    from jupyter_storage_explorer.operations import FileSystemOperations

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


def _version(data: bytes) -> str:
    """Identifies file contents, to detect changes made elsewhere while editing."""
    return hashlib.sha256(data).hexdigest()


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
        "name": _paths.basename(info["name"]),
        "path": _paths.norm(info["name"]),
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else info.get("size"),
        "mtime": mtime,
    }


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
    opens text files in an editor that saves back to the storage, "Download
    to local" saves the selected files (not folders) in the browser, and
    "Download to JupyterLab" copies them into a folder of the Jupyter server.
    "Copy" and "Paste" copy files into a folder, also between explorers (see
    ``_paste_task``), and "Delete" deletes files. Files
    dragged from JupyterLab's file browser or from the user's computer onto
    the list or tree are uploaded after a confirmation, and files dragged
    within the widget onto a folder are moved there. Folders
    are moved, copied, pasted and deleted only in "Unsafe mode", turned on
    in the status bar and off again by any operation.

    Moving, deleting, pasting and downloading to JupyterLab run in the
    background, one at a time, with their progress shown and a button to
    cancel them; the explorer stays usable meanwhile. They are done by
    ``operations``, a list of ``FileSystemOperations`` objects (see
    operations.py): the first that supports an operation for the filesystem
    does it. By default ``default_operations()``: with fsspec, many files at
    a time on asynchronous filesystems (e.g. s3fs). A list given replaces
    it; put objects of your own before the defaults to do some operations
    differently, e.g. server-side copies with a storage's own client, or
    deleting into a trash folder::

        StorageExplorer(url, operations=[MyOps(), *StorageExplorer.default_operations()])

    Examples:
        StorageExplorer()                          # current local directory
        StorageExplorer("s3://my-bucket/data", anon=True)
        StorageExplorer("memory://")
        StorageExplorer("data", fs=my_filesystem)  # an existing fsspec filesystem
        StorageExplorer(filesystems={"Lake": s3, "Local": "file:///home/me/data"})

    Extra keyword arguments are passed to fsspec as storage options.
    When ``fs`` is given, ``path`` is a path within that filesystem instead.

    ``filesystems`` maps names to several filesystems, chosen with a
    drop-down in the widget; each
    remembers its current folder while another is shown. Values are fsspec
    filesystems (starting at their top level; wrap one in fsspec's
    ``DirFileSystem`` to start in a subfolder) or URLs (starting at that path).
    It cannot be combined with ``path``, ``fs`` or storage options.

    ``height`` is the height of the tree and file list; the preview panel adds
    to it. ``height="fill"`` makes the explorer as tall as its container
    instead, e.g. the tab opened from JupyterLab's launcher (not a notebook
    cell, which has no height of its own). ``formats`` replaces the formats
    that can be previewed (default: ``default_formats()``). Or
    ``format_options`` gives keyword arguments to create every default
    format with, each using those it takes, e.g.
    ``{"polars_storage_options": {...}, "polars_delta_use_pyarrow": True}``;
    it cannot be combined with ``formats``. ``max_upload_bytes`` limits the
    size of files uploaded from the user's computer (default 10 MB; None for
    no limit).

    ``allow_download_to_local=False`` leaves "Download to local" out of the menu
    (and the kernel refuses it). ``download_to_jupyterlab_path`` is the folder
    "Download to JupyterLab" copies into, on the kernel's machine: by default
    ".", the folder the explorer is launched in; e.g. "~/Downloads". Relative
    paths and "~" are resolved when the explorer is created. None leaves the
    item out.

    The file list is filtered, sorted and paged in the browser, from the whole
    listing of the folder shown. Folders of more than ``max_browser_items``
    items (default 20,000; None for no limit) are handled by the kernel
    instead, which sends one page at a time (see ``listing.Listing``): less to
    send, but each change of filter, sort or page waits for the kernel.

    The public interface is ``folder_url``, the URL of the folder shown, and
    ``selected_urls``, those of the selected items. To change how paths
    become locations ("Copy URL", these properties, "Python code" snippets,
    data read by polars), override ``_url`` in a subclass.

    With polars installed, tabular data (Parquet, Delta Lake, CSV, ...) opens
    in a data browser ("Query data") with paging, sorting, filters and column
    selection. Its settings are remembered per dataset by ``query_settings``
    (a ``QuerySettingsStore``; by default shared by the explorers in the
    kernel, in memory; give one with a path to keep them across restarts).
    """

    _esm = _static.esm("storage_explorer")
    _css = _static.css("storage_explorer")

    _root = traitlets.Unicode().tag(sync=True)
    # Directory path -> list of {"name", "path"} of its subdirectories, with
    # "no_url": true for those without a URL (see _url). A directory that has
    # not been listed yet has no key.
    _tree = traitlets.Dict().tag(sync=True)
    _current_dir = traitlets.Unicode().tag(sync=True)
    # The items in the current directory, as columns (see _make_listing): large
    # folders are listed whole, and a list of objects repeating the keys, the
    # folder's path and each URL was several times larger. For folders of more
    # than max_browser_items, only {"dir", "query": true, "total", "version"}:
    # the frontend asks for pages ("list"), filtered and sorted by the kernel;
    # "version" changes when the listing does.
    _listing = traitlets.Dict().tag(sync=True)
    _selected = traitlets.List(traitlets.Unicode()).tag(sync=True)
    _error = traitlets.Unicode().tag(sync=True)
    # Height of the tree and file list (CSS). The preview panel adds its own
    # height below them, and both can be resized by dragging in the widget.
    _height = traitlets.Unicode("400px").tag(sync=True)
    # Preview shown in the panel: {"path", "name", "format", "sections",
    # "error", "loading"}; empty when the panel is closed.
    _preview = traitlets.Dict().tag(sync=True)
    # Format name -> label shown to the user, e.g. {"delta": "Delta Lake table"}.
    _format_labels = traitlets.Dict().tag(sync=True)
    # Format name of the current directory itself (e.g. "delta"), or ""
    # if it cannot be previewed; enables the Preview button when nothing is selected.
    _current_format = traitlets.Unicode().tag(sync=True)
    # Whether the current directory can be queried in the data browser
    # ("Query data" instead of "Preview").
    _current_query = traitlets.Bool().tag(sync=True)
    # Format of the single selected item, for the Preview button's label:
    # {"path", "format", "query"} ("format" is "" if it cannot be previewed;
    # "query": whether it opens in the data browser); empty unless exactly one
    # item is selected. The path lets the frontend ignore an answer for a
    # previous selection.
    _selected_format = traitlets.Dict().tag(sync=True)
    # Largest file that can be uploaded from the user's computer (bytes), or
    # None for no limit. Files dragged from JupyterLab's file browser are
    # copied by the kernel directly and are not limited.
    _max_upload_bytes = traitlets.Int(10 * 1024 * 1024, allow_none=True).tag(sync=True)
    # Names of the filesystems to choose from, and the one shown. The
    # widget's drop-down sets `_filesystem` to switch.
    _filesystem_names = traitlets.List(traitlets.Unicode()).tag(sync=True)
    _filesystem = traitlets.Unicode().tag(sync=True)
    # The "Unsafe mode" switch in the status bar: while on, risky operations
    # are offered (today: moving, copying, pasting and deleting folders). The
    # frontend turns it off when any operation starts, and sends with each
    # request whether it was on ("unsafe").
    _unsafe_mode = traitlets.Bool(False).tag(sync=True)
    # Identifies this explorer to "Paste": files copied in it, from the
    # filesystem shown, are copied within that filesystem.
    _explorer_id = traitlets.Unicode().tag(sync=True)
    # Whether "Download to local" (files saved by the browser) is offered.
    _allow_download_to_local = traitlets.Bool(True).tag(sync=True)
    # Absolute folder on the kernel's machine "Download to JupyterLab" copies
    # into, or "" when it is not offered.
    _download_to_jupyterlab_path = traitlets.Unicode().tag(sync=True)

    def __init__(
        self,
        path: str | None = None,
        *,
        fs: AbstractFileSystem | None = None,
        filesystems: Mapping[str, AbstractFileSystem | str] | None = None,
        height: str = "400px",
        formats: Sequence[DataFormat] | None = None,
        format_options: Mapping[str, Any] | None = None,
        preview_limits: PreviewLimits | None = None,
        max_upload_bytes: int | None = 10 * 1024 * 1024,
        allow_download_to_local: bool = True,
        download_to_jupyterlab_path: str | None = ".",
        query_settings: QuerySettingsStore | None = None,
        max_browser_items: int | None = 20_000,
        operations: Sequence[FileSystemOperations] | None = None,
        **storage_options: Any,
    ) -> None:
        self._query_settings = query_settings or default_query_settings
        self._max_browser_items = max_browser_items
        # How files are moved, copied, deleted and downloaded (see operations.py),
        # and the jobs doing it in the background (see jobs.py).
        self._operations = OperationChain(
            self.default_operations() if operations is None else operations
        )
        self._jobs = JobRunner(self._send_job)
        # The current directory's items, kept for "list" requests (and paths).
        self._full_listing = Listing(self._make_listing("", []))
        self._listing_version = 0
        # Data browser: path -> the data being queried.
        self._queries: dict[str, DataQuery] = {}
        self._formats = explorer_formats(formats, format_options)
        self._preview_limits = preview_limits or PreviewLimits()
        # Files being received from the user's computer (see incoming.py).
        self._incoming = IncomingFiles(max_upload_bytes)
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
        self._fs: AbstractFileSystem = self._filesystems[name][0]
        super().__init__(
            _height=height,
            _format_labels={f.name: f.label for f in self._formats},
            _max_upload_bytes=max_upload_bytes,
            _filesystem_names=list(self._filesystems),
            _explorer_id=uuid.uuid4().hex,
            _allow_download_to_local=allow_download_to_local,
            # Resolved now: "." is the folder the explorer is launched in,
            # even if the kernel's working directory changes later.
            _download_to_jupyterlab_path=""
            if download_to_jupyterlab_path is None
            else os.path.abspath(os.path.expanduser(download_to_jupyterlab_path)),
        )
        self.on_msg(self._on_custom_msg)
        self._filesystem = name  # shows its top level (see _on_filesystem)

    @staticmethod
    def default_operations() -> list[FileSystemOperations]:
        """The file operations used unless ``operations`` is given: on
        asynchronous fsspec filesystems (s3fs, gcsfs, adlfs, ...) many files
        at a time (``AsyncFsspecOperations``), and everything else with fsspec
        (``FsspecOperations``). New objects each time."""
        return [AsyncFsspecOperations(), FsspecOperations()]

    @traitlets.validate("_filesystem")
    def _validate_filesystem(self, proposal: dict[str, Any]) -> str:
        if proposal["value"] not in self._filesystems:
            raise traitlets.TraitError(
                f"unknown filesystem {proposal['value']!r}; choose from {list(self._filesystems)}"
            )
        return proposal["value"]

    @traitlets.observe("_filesystem")
    def _on_filesystem(self, change: dict[str, Any]) -> None:
        """Switch filesystems, remembering the folder left and returning to the one remembered."""
        if change["old"] in self._filesystems:
            self._remembered[change["old"]] = self._current_dir
        self._fs, root = self._filesystems[change["new"]]
        path = self._remembered.get(change["new"], root)
        if path != root:
            try:
                gone = not self._isdir(path)
            except Exception:
                gone = True  # cannot tell: start at the top rather than fail the switch
            if gone:
                path = root  # the remembered folder is gone
        # One update for the frontend: separate ones would let it combine the
        # new root with the old folder (or the reverse) and ask the new
        # filesystem to list the old filesystem's paths.
        self._queries.clear()
        with self.hold_sync():
            self._preview = {}
            self._tree = {}
            self._root = root
            if self._current_dir == path:
                # Same path string as before (e.g. "/" on both), so no change event lists it.
                self._list(path)
            else:
                self._current_dir = path

    # --- Public interface ---

    @property
    def folder_url(self) -> str | None:
        """Location of the folder shown in the list (see ``_url``), usable with
        ``fsspec.open``, pandas, etc.; None if it has no URL."""
        return self._url(self._current_dir)

    @property
    def selected_urls(self) -> list[str]:
        """Locations of the selected items (see ``_url``), in the order selected.

        Items without a URL are left out, so the list is empty when nothing
        with a URL is selected.
        """
        return [url for p in self._selected if (url := self._url(p)) is not None]

    # --- Messages from the frontend ---

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
            "refresh": lambda c, _: self._refresh(),
            "preview": lambda c, _: self._open_preview(c["path"], c.get("format")),
            "menu_info": lambda c, _: self._send_menu_info(c["path"]),
            "edit_open": lambda c, _: self._edit_open(c["path"]),
            "edit_save": lambda c, _: self._edit_save(
                c["path"], c["text"], c.get("version")
            ),
            "download": lambda c, _: self._download(c["paths"]),
            "upload": lambda c, _: self._reply(c, self._upload_request(c)),
            "upload_check": lambda c, _: self._reply(
                c, self._upload_check(c["dest"], c["names"])
            ),
            "upload_chunk": lambda c, b: self._reply(c, self._upload_chunk(c, b)),
            "vendor": lambda c, _: self._reply(c, self._vendor_source(c["name"])),
            # The listing has no URLs (see _make_listing): asked for when copying.
            "urls": lambda c, _: self._reply(
                c, {"urls": [self._url(p) for p in c["paths"]]}
            ),
            "list": lambda c, _: self._reply(c, self._list_page(c)),
            "job_cancel": lambda c, _: self._cancel_job(c),
            "move": lambda c, _: self._reply(c, self._move_request(c)),
            "download_to_server": lambda c, _: self._reply(
                c, self._download_to_server_request(c)
            ),
            "delete": lambda c, _: self._reply(c, self._delete_request(c)),
            "paste": lambda c, _: self._reply(c, self._paste_request(c)),
            "create_folder": lambda c, _: self._reply(
                c, self._create_folder_request(c)
            ),
            "download_to_jupyterlab": lambda c, _: self._reply(
                c, self._download_to_jupyterlab_request(c)
            ),
            "query_rows": lambda c, _: self._reply(c, self._query_request(c)),
            "query_check": lambda c, _: self._reply(c, self._query_request(c)),
            "query_save": lambda c, _: self._reply(c, self._query_request(c)),
            "query_reload": lambda c, _: self._reply(c, self._query_request(c)),
            "query_mode": lambda c, _: self._reply(c, self._query_request(c)),
        }

    def _reply(self, content: dict[str, Any], result: dict[str, Any]) -> None:
        """Answer a request the frontend waits for, matched by its "rid"."""
        self.send({"type": "reply", "rid": content["rid"], **result})

    def _vendor_source(self, name: str) -> dict[str, Any]:
        """Source of a bundled library, e.g. marked for Markdown previews."""
        if name not in _VENDOR_FILES:
            return {"error": f"unknown library {name!r}"}
        return {
            "source": (_static.STATIC / "vendor" / name).read_text(encoding="utf-8")
        }

    # --- File list and tree ---

    @traitlets.observe("_current_dir")
    def _on_current_dir(self, change: dict[str, Any]) -> None:
        self._list(change["new"])

    def _list(self, path: str) -> None:
        # Make sure the tree can be expanded down to the current directory.
        for ancestor in self._ancestors(path):
            if ancestor not in self._tree:
                self._load_children(ancestor)
        try:
            infos = self._ls(path)
        except Exception as exc:
            self._error = f"Cannot list {path}: {exc}"
            self._show_listing(self._make_listing(path, []))
            self._selected = []
            self._current_format = ""
            self._current_query = False
            return
        self._error = ""
        self._set_children(path, infos)
        self._show_listing(self._make_listing(path, infos))
        self._selected = []
        fmt = self._directory_format(path, infos)
        self._current_format = fmt.name if fmt is not None else ""
        self._current_query = fmt is not None and fmt.can_query()

    def _ancestors(self, path: str) -> list[str]:
        """Directories from the root down to (but excluding) ``path``."""
        if not path.startswith(self._root):
            return []
        out, cur = [], self._root
        for segment in filter(None, path[len(self._root) :].split("/")):
            out.append(cur)
            cur = _paths.join(cur, segment)
        return out

    def _load_children(self, path: str) -> None:
        try:
            infos = self._ls(path)
        except Exception as exc:
            self._error = f"Cannot list {path}: {exc}"
            infos = []
        self._set_children(path, infos)

    def _set_children(self, path: str, infos: list[dict[str, Any]]) -> None:
        dirs = []
        for info in infos:
            if info.get("type") == "directory":
                child = _paths.norm(info["name"])
                dirs.append({"name": _paths.basename(child), "path": child})
                if self._url(child) is None:
                    dirs[-1]["no_url"] = True
        dirs.sort(key=lambda d: d["name"].lower())
        self._tree = {**self._tree, path: dirs}

    def _make_listing(self, path: str, infos: list[dict[str, Any]]) -> dict[str, Any]:
        """The listing of directory ``path`` (its ``infos`` from ``_ls``) for ``_listing``.

        One list per column, an item per entry: "names", "is_dir" (0 or 1),
        "sizes" (None for folders), "mtimes" (whole seconds, or None), and
        "format", an index into "formats", whose first name is "" (none; all
        folders). Paths are not sent: an entry's is "dir" joined with its name,
        unless "paths" (otherwise None) gives them all, for a filesystem that
        names them differently. URLs are not sent either, as most are never
        used: the frontend asks for them ("urls") when copying; "no_url" lists
        the indexes of the entries without one (see _url).
        """
        listing: dict[str, Any] = {
            "dir": path,
            "names": [],
            "is_dir": [],
            "sizes": [],
            "mtimes": [],
            "formats": [""],
            "format": [],
            "paths": None,
            "no_url": [],
        }
        format_index = {"": 0}
        paths = []
        for i, info in enumerate(infos):
            entry = _entry(info)
            fmt = self._file_format(info)
            if fmt not in format_index:
                format_index[fmt] = len(listing["formats"])
                listing["formats"].append(fmt)
            listing["names"].append(entry["name"])
            listing["is_dir"].append(int(entry["type"] == "directory"))
            listing["sizes"].append(entry["size"])
            mtime = entry["mtime"]
            listing["mtimes"].append(None if mtime is None else int(mtime))
            listing["format"].append(format_index[fmt])
            paths.append(entry["path"])
            if self._url(entry["path"]) is None:
                listing["no_url"].append(i)
        if any(
            p != _paths.join(path, n)
            for p, n in zip(paths, listing["names"], strict=True)
        ):
            listing["paths"] = paths
        return listing

    def _show_listing(self, columns: dict[str, Any]) -> None:
        """Keep the current directory's ``columns`` (see _make_listing) and show them."""
        self._full_listing = Listing(columns)
        self._send_listing()

    def _send_listing(self) -> None:
        """Send the current directory's listing, or for a large folder only its
        size, the frontend then asking for pages ("list")."""
        listing = self._full_listing
        self._listing_version += 1
        limit = self._max_browser_items
        if limit is not None and len(listing) > limit:
            self._listing = {
                "dir": listing.dir,
                "query": True,
                "total": len(listing),
                "version": self._listing_version,
            }
        else:
            self._listing = listing.columns

    def _list_page(self, content: dict[str, Any]) -> dict[str, Any]:
        """A page of a large folder's items: the "list" request (see Listing.query).

        {"stale": true} if the folder shown has changed since the frontend asked.
        """
        listing = self._full_listing
        if content.get("dir") != listing.dir or content.get("version") != (
            self._listing.get("version")
        ):
            return {"stale": True}
        return listing.query(
            text=content.get("text") or "",
            regex=bool(content.get("regex")),
            sort=content.get("sort", "name"),
            asc=content.get("asc", True),
            page=int(content.get("page", 0)),
            page_size=int(content.get("page_size", 100)),
        )

    def _listed_paths(self) -> list[str]:
        """Paths of the current directory's items, in listing order."""
        columns = self._full_listing.columns
        if columns["paths"] is not None:
            return columns["paths"]
        return [_paths.join(columns["dir"], name) for name in columns["names"]]

    def _refresh(self) -> None:
        """Drop cached listings and reload the current directory."""
        self._invalidate_cache()
        self._tree = {}
        self._list(self._current_dir)

    def _refresh_dir(self, path: str) -> None:
        """Show changes made to directory ``path`` in the list and tree."""
        self._invalidate_cache(path)
        if path == self._current_dir:
            self._list(path)
        elif path in self._tree:
            self._load_children(path)

    def _forget(self, path: str, moved_to: str | None = None) -> None:
        """Let the widget follow folder or file ``path``, moved to ``moved_to`` or deleted.

        Closes a preview of it or of something in it, drops its folders from the
        tree, and if the list shows it (or a folder in it), shows the same
        folder where it was moved to, or the deleted folder's parent.
        """
        if _paths.inside(self._preview.get("path") or "", path):
            self._close_preview()
        self._tree = {k: v for k, v in self._tree.items() if not _paths.inside(k, path)}
        if _paths.inside(self._current_dir, path):
            self._current_dir = (
                _paths.parent(path, self._fs)
                if moved_to is None
                else moved_to + _paths.norm(self._current_dir)[len(_paths.norm(path)) :]
            )

    def _update_entry(self, path: str) -> None:
        """Refresh the size and modification time shown for ``path`` in the list."""
        paths = self._listed_paths()
        if path in paths:
            entry = _entry(self._info(path))
            mtime = None if entry["mtime"] is None else int(entry["mtime"])
            self._full_listing.update(paths.index(path), entry["size"], mtime)
            self._send_listing()

    def _file_format(self, info: dict[str, Any]) -> str:
        """The format name of a listed file, e.g. "json-lines".

        Shown as the row's ``data-file-format``. Empty for folders (detecting
        them would mean listing each one), files without a URL and
        unrecognised files.
        """
        path = _paths.norm(info["name"])
        if info.get("type") == "directory" or (url := self._url(path)) is None:
            return ""
        target = Target(fs=self._fs, path=path, url=url, info=info)
        try:
            fmt = detect_format(target, self._formats)
        except Exception:
            return ""  # detection is best-effort
        return fmt.name if fmt is not None else ""

    def _directory_format(
        self, path: str, infos: list[dict[str, Any]]
    ) -> DataFormat | None:
        """The format of directory ``path`` given its listing, if any."""
        url = self._url(path)
        if url is None:
            return None
        # The listing is all directory formats need, so skip fetching the
        # directory's own info.
        target = Target(
            fs=self._fs,
            path=path,
            url=url,
            info={"name": path, "type": "directory"},
            children=infos,
        )
        try:
            return detect_format(target, self._formats)
        except Exception:
            return None  # detection is best-effort; a failure just means no preview

    @traitlets.observe("_selected")
    def _on_selected(self, change: dict[str, Any]) -> None:
        if len(change["new"]) != 1:
            self._selected_format = {}
            return
        path = change["new"][0]
        try:
            _, formats = self._detect(path)
        except Exception:
            formats = []  # detection is best-effort; a failure just means no preview
        self._selected_format = {
            "path": path,
            "format": formats[0].name if formats else "",
            "query": bool(formats) and formats[0].can_query(),
        }

    # --- Locations: how paths become URLs (override _url to change them) ---

    def _url(self, path: str) -> str | None:
        """Location of ``path`` on the filesystem shown (``self._fs``).

        The one place paths become locations: "Copy URL", ``folder_url``,
        "Python code" snippets and previews that read by location all use it.
        Gives a plain path for local files, which every library reads; for
        Azure (adlfs), ``abfs://container@account.dfs.core.windows.net/key``,
        which names the account; and ``protocol://path`` otherwise. Override
        to e.g. resolve a ``DirFileSystem`` to its underlying location; with
        several ``filesystems``, tell them apart by ``self._filesystem``.

        An override may return None for items without a URL. They can still be
        browsed, uploaded to, downloaded and moved, but have no "Copy URL",
        preview, "Query data", "Python code" or "Edit".
        """
        return default_url(self._fs, path)

    # --- Preview, data browser ("Query data") and the right-click menu ---

    def _detect(self, path: str) -> tuple[Target | None, list[DataFormat]]:
        """The target at ``path`` and the formats matching it, best first.

        (None, []) if ``path`` has no URL: it is then not treated as data.
        """
        url = self._url(path)
        if url is None:
            return None, []
        info = self._info(path)
        children = self._ls(path) if info.get("type") == "directory" else None
        target = Target(fs=self._fs, path=path, url=url, info=info, children=children)
        return target, matching_formats(target, self._formats)

    def _open_preview(self, path: str, format: str | None = None) -> None:
        """Preview the file or directory at ``path`` in the preview panel.

        ``format`` names one of the formats matching it (e.g. "text" for a JSON
        file); by default the best match is used.
        """
        base = {
            "path": path,
            "name": _paths.basename(path),
            "format": None,
            "sections": [],
            "error": "",
        }
        # Shown while the (possibly remote) reads below run.
        self._preview = {**base, "loading": True}
        try:
            target, formats = self._detect(path)
            if target is None:
                raise ValueError(f"{path} has no URL, so it cannot be previewed")
            if format is not None:
                formats = [f for f in formats if f.name == format]
                if not formats:
                    raise ValueError(f"{path} cannot be previewed as {format}")
            if formats:
                fmt = formats[0]
                base["format"] = fmt.name
                if fmt.can_query():
                    base["query"] = self._open_query(path, fmt, target)
                else:
                    base["sections"] = [
                        _section(s) for s in fmt.preview(target, self._preview_limits)
                    ]
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
        self._preview = base

    def _close_preview(self) -> None:
        self._queries.clear()
        self._preview = {}

    def _open_query(self, path: str, fmt: DataFormat, target: Target) -> dict[str, Any]:
        """Open ``path`` in the data browser: its columns and remembered settings.

        The frontend then asks for rows with "query_rows".
        """
        # Settings are remembered by URL, so they follow the data across explorers.
        data = DataQuery(
            functools.partial(fmt.scan, target.url, target.is_dir),
            target.url,
            self._query_settings,
        )
        self._queries[path] = data
        return data.opening()

    def _query_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer the data browser's "query_rows", "query_check" or "query_save"."""
        data = self._queries.get(content["path"])
        if data is None:
            return {"error": "the data is no longer open; preview it again"}
        return data.handle(content) or {}

    def _recipes(self, path: str) -> list[Recipe]:
        """Ways to load ``path`` in the notebook, from its best-matching format.

        Empty if its format is unknown or it has no URL.
        """
        target, formats = self._detect(path)
        if target is None or not formats:
            return []
        return formats[0].recipes(target)

    def _send_menu_info(self, path: str) -> None:
        """Answer the right-click menu's request: matching formats ("Preview as"),
        load code ("Python code") and whether it can be edited ("Edit")."""
        reply: dict[str, Any] = {"type": "menu_info", "path": path}
        try:
            target, formats = self._detect(path)
            reply["formats"] = [f.name for f in formats]
            reply["recipes"] = (
                [dataclasses.asdict(r) for r in formats[0].recipes(target)]
                if formats
                else []
            )
            reply["editable"] = (
                target is not None
                and not target.is_dir
                and any(isinstance(f, Text) for f in formats)
            )
            reply["query"] = bool(formats) and formats[0].can_query()
        except Exception as exc:
            reply["error"] = f"{type(exc).__name__}: {exc}"
        self.send(reply)

    # --- Text editor ---

    def _edit_open(self, path: str) -> None:
        reply: dict[str, Any] = {"type": "edit_open", "path": path}
        try:
            reply["text"], reply["version"] = self._read_text(path)
        except Exception as exc:
            reply["error"] = f"Cannot open {_paths.basename(path)}: {exc}"
        self.send(reply)

    def _edit_save(self, path: str, text: str, version: str | None) -> None:
        reply: dict[str, Any] = {"type": "edit_save", "path": path}
        try:
            reply["version"] = self._write_text(path, text, version)
        except Exception as exc:
            reply["error"] = f"Cannot save: {exc}"
        self.send(reply)

    def _read_text(self, path: str) -> tuple[str, str]:
        """The text of a UTF-8 file, and a version string to pass to ``_write_text``."""
        data = self._read_bytes(path)
        if len(data) > _MAX_EDIT_BYTES:
            raise ValueError(
                f"too large to edit (over {_MAX_EDIT_BYTES // (1024 * 1024)} MB)"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("not UTF-8 text") from None
        return text, _version(data)

    def _write_text(self, path: str, text: str, version: str | None = None) -> str:
        """Save ``text`` to the file at ``path``; returns its new version.

        With ``version`` (from ``_read_text``), refuses to save if the file has
        changed since, rather than overwriting that change. Files with Windows
        line endings keep them, although browsers edit text with "\\n" only.
        """
        current = self._read_bytes(path) if self._exists(path) else b""
        if version is not None and _version(current) != version:
            raise RuntimeError(
                "the file has changed since it was opened; close the editor and open it again"
            )
        if b"\r\n" in current:
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        data = text.encode("utf-8")
        self._write_bytes(path, data)
        self._update_entry(path)
        if self._preview.get("path") == path:
            self._open_preview(path, self._preview.get("format"))
        return _version(data)

    # --- Download to local: the browser saves the files on the user's computer ---

    def _download(self, paths: list[str]) -> None:
        """Send each file to the browser, which saves it; one message per file."""
        for path in paths:
            reply: dict[str, Any] = {
                "type": "download",
                "path": path,
                "name": _paths.basename(path),
            }
            try:
                if not self._allow_download_to_local:
                    raise PermissionError("downloading to local is not allowed")
                info = self._info(path)
                if info.get("type") == "directory":
                    raise ValueError("folders cannot be downloaded")
                size = info.get("size")
                if size is not None and size > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"too large to download (over {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB)"
                    )
                data = self._read_bytes(path)
            except Exception as exc:
                reply["error"] = f"{_paths.basename(path)}: {exc}"
                self.send(reply)
            else:
                self.send(reply, [data])

    # --- Jobs: move, delete, paste, upload and download run in the
    # background. Each is planned by FileTasks (file_tasks.py), its work runs
    # in a job's worker thread (jobs.py), and once it has ended, _finish shows
    # what it changed, back on the main thread ---

    def _tasks(self) -> FileTasks:
        """Plans operations on the filesystem shown."""
        return FileTasks(self._fs, self._root, self._operations)

    def _start(self, plan: Plan) -> dict[str, Any]:
        """Run ``plan`` as a job: {"job": its id}; or the reply as it is if
        there is nothing to run (e.g. {"conflicts": [...]} to ask about)."""
        if isinstance(plan, dict):
            return plan
        job = self._jobs.submit(
            plan.kind, plan.title, plan.work, lambda job: self._finish(plan)
        )
        return {"job": job.id}

    def _run_now(self, plan: Plan) -> dict[str, Any]:
        """Run ``plan`` in this thread, without a job (e.g. from Python): its result."""
        if isinstance(plan, dict):
            return plan
        try:
            return plan.work(Progress())
        finally:
            self._finish(plan)

    def _finish(self, task: Task) -> None:
        """After ``task``, whatever its outcome: follow what it moved or
        removed, and show the folders it changed."""
        if task.cleanup is not None:
            task.cleanup()
        if task.fs is not self._fs:
            task.fs.invalidate_cache()  # the user has switched filesystems
            return
        for source, target in task.moved:
            self._forget(source, moved_to=target)
        for path in task.removed:
            self._forget(path)
        for folder in task.changed:
            self._refresh_dir(folder)

    def _send_job(self, job: Job) -> None:
        """Tell the frontend how ``job`` is doing (see Job.snapshot)."""
        self.send({"type": "job", **job.snapshot()})

    def _cancel_job(self, content: dict[str, Any]) -> None:
        self._jobs.cancel(content.get("id", ""))

    def _plan_request(self, plan: Callable[[], Plan]) -> dict[str, Any]:
        """Answer a request for an operation: start ``plan()``, or say why not."""
        try:
            return self._start(plan())
        except Exception as exc:
            return {"errors": [f"{type(exc).__name__}: {exc}"]}

    # --- Move: files (and, in unsafe mode, folders) dragged onto a folder;
    # delete: chosen with "Delete" in the right-click menu ---

    def _move_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().move(
                content["paths"],
                content["dest"],
                content.get("if_exists", "ask"),
                folders=bool(content.get("unsafe")),
            )
        )

    def _move(
        self,
        paths: Sequence[str],
        dest: str,
        if_exists: str = "ask",
        folders: bool = False,
    ) -> dict[str, Any]:
        """Move files into folder ``dest``, now (see ``FileTasks.move``)."""
        return self._run_now(self._tasks().move(paths, dest, if_exists, folders))

    def _delete_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().delete(
                content["paths"], folders=bool(content.get("unsafe"))
            )
        )

    def _delete(self, paths: Sequence[str], folders: bool = False) -> dict[str, Any]:
        """Delete files, now (see ``FileTasks.delete``)."""
        return self._run_now(self._tasks().delete(paths, folders))

    # --- Paste: files (and, in unsafe mode, folders) copied with "Copy" (in any
    # explorer), into a folder ---

    def _paste_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "paste": files copied in the explorer ``content["explorer"]``,
        from its filesystem ``content["filesystem"]``."""
        same = (
            content.get("explorer") == self._explorer_id
            and content.get("filesystem") == self._filesystem
        )
        return self._plan_request(
            lambda: self._tasks().paste(
                content["files"],
                content["dest"],
                content.get("if_exists", "ask"),
                same_filesystem=same,
                folders=bool(content.get("unsafe")),
            )
        )

    def _paste(
        self,
        files: Sequence[dict[str, Any]],
        dest: str,
        if_exists: str = "ask",
        same_filesystem: bool = False,
        folders: bool = False,
    ) -> dict[str, Any]:
        """Copy files into folder ``dest``, now (see ``FileTasks.paste``)."""
        return self._run_now(
            self._tasks().paste(files, dest, if_exists, same_filesystem, folders)
        )

    # --- Upload: files (and, in unsafe mode, folders) dragged in from
    # JupyterLab's file browser, which the kernel copies itself ---

    def _upload_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "upload": ``paths`` are relative to JupyterLab's server folder ``root``."""
        base = os.path.expanduser(content["root"])
        sources = [os.path.join(base, *p.split("/")) for p in content["paths"]]
        return self._plan_request(
            lambda: self._tasks().upload(
                sources,
                content["dest"],
                content.get("if_exists", "ask"),
                folders=bool(content.get("unsafe")),
            )
        )

    def _upload_files(
        self,
        sources: Sequence[str],
        dest: str,
        if_exists: str = "ask",
        folders: bool = False,
    ) -> dict[str, Any]:
        """Copy local files into folder ``dest``, now (see ``FileTasks.upload``)."""
        return self._run_now(self._tasks().upload(sources, dest, if_exists, folders))

    # --- Upload from the user's computer: the browser sends files in pieces
    # (see incoming.py); the last one starts a job copying the whole file ---

    def _upload_check(self, dest: str, names: list[str]) -> dict[str, Any]:
        """Which of ``names`` already exist in ``dest``."""
        return {
            "conflicts": [
                n for n in names if self._exists(_paths.join(dest, _paths.safe_name(n)))
            ]
        }

    def _upload_chunk(
        self, content: dict[str, Any], buffers: list[Any]
    ) -> dict[str, Any]:
        """Add one piece of a file; the last one starts a job copying the file
        to the storage: {"job": id}. The frontend stops sending a file after
        an error ({"error": ...})."""
        upload_id = content["id"]
        try:
            target = _paths.join(content["dest"], _paths.safe_name(content["name"]))
            piece = bytes(buffers[0]) if buffers else None
            self._incoming.add(upload_id, piece, target, self._fs)
            if not content["last"]:
                return {}
            incoming = self._incoming.pop(upload_id)
        except Exception as exc:
            self._incoming.discard(upload_id)
            return {"error": f"{_paths.basename(content['name'])}: {exc}"}
        tasks = FileTasks(incoming.fs, self._root, self._operations)
        return self._start(tasks.upload_file(incoming.path, incoming.target))

    # --- Create a folder: "Create a folder" in the right-click menu ---

    def _create_folder_request(self, content: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._create_folder(content["dest"], content["name"])
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _create_folder(self, dest: str, name: str) -> dict[str, Any]:
        """Create folder ``name`` (a name, not a path) in folder ``dest``, with
        the operations' ``mkdir`` (quick: not a job).

        Returns {"created": name}, with "hidden": True when the new folder does
        not show, as on object stores (S3, Google Cloud Storage), which have no
        empty folders; or {"error": reason}.
        """
        if (error := _paths.folder_name_error(name)) is not None:
            return {"error": error}
        path = _paths.join(dest, name)
        if self._exists(path):
            return {"error": f"{name} already exists"}  # the dialog shows where
        self._operations.mkdir(self._fs, path)
        self._refresh_dir(dest)
        return {"created": name, "hidden": not self._isdir(path)}

    # --- Download to the Jupyter server: "Download to JupyterLab", and files
    # dropped on JupyterLab's file browser ---

    def _download_to_jupyterlab_request(
        self, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer "download_to_jupyterlab": copy into ``download_to_jupyterlab_path``."""
        if not self._download_to_jupyterlab_path:
            return {"errors": ["downloading to JupyterLab is not allowed"]}
        return self._plan_request(
            lambda: self._tasks().download(
                content["paths"],
                self._download_to_jupyterlab_path,
                content.get("if_exists", "ask"),
            )
        )

    def _download_to_server_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "download_to_server": ``dest`` is relative to the server's folder ``root``."""
        dest = os.path.join(
            os.path.expanduser(content["root"]),
            *filter(None, content["dest"].split("/")),
        )
        return self._plan_request(
            lambda: self._tasks().download(
                content["paths"], dest, content.get("if_exists", "ask")
            )
        )

    def _copy_to_folder(
        self, paths: Sequence[str], dest: str, if_exists: str = "ask"
    ) -> dict[str, Any]:
        """Copy files into ``dest`` on the kernel's machine, now (see ``FileTasks.download``)."""
        return self._run_now(self._tasks().download(paths, dest, if_exists))

    # --- File operations: wrappers of fsspec calls on the filesystem shown
    # (``self._fs``) for listing, reading and writing; the methods above go
    # through them, never through fsspec directly. Moving, copying and
    # deleting go through the operations objects instead (see operations.py) ---

    def _ls(self, path: str) -> list[dict[str, Any]]:
        """The items in directory ``path`` (fsspec's ``ls(detail=True)`` entries)."""
        infos = self._fs.ls(path, detail=True)
        # Some backends include the directory itself in its own listing.
        return [i for i in infos if _paths.norm(i["name"]) != _paths.norm(path)]

    def _info(self, path: str) -> dict[str, Any]:
        return self._fs.info(path)

    def _exists(self, path: str) -> bool:
        return self._fs.exists(path)

    def _isdir(self, path: str, fs: AbstractFileSystem | None = None) -> bool:
        """Whether ``path`` is a directory; False if it does not exist (fsspec
        returns False on OSError, e.g. not found or access denied).

        ``fs``: another filesystem than the one shown, e.g. a pasted file's.
        """
        return (fs or self._fs).isdir(path)

    def _read_bytes(self, path: str) -> bytes:
        return self._fs.cat_file(path)

    def _write_bytes(self, path: str, data: bytes) -> None:
        self._fs.pipe_file(path, data)
        self._fs.invalidate_cache(path)

    def _put_file(
        self, local_path: str, path: str, fs: AbstractFileSystem | None = None
    ) -> None:
        """Copy the local file ``local_path`` to ``path``; streams, so any size works.

        ``fs``: another filesystem than the one shown, e.g. the one an upload
        started on, as the user may switch filesystems meanwhile.
        """
        (fs or self._fs).put_file(local_path, path)

    def _invalidate_cache(self, path: str | None = None) -> None:
        """Forget cached listings (of ``path``, else all), so changes made elsewhere show."""
        self._fs.invalidate_cache(path)
