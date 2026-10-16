"""Storage explorer widget: directory tree, file list, and a preview of the selected item."""

from __future__ import annotations

import base64
import dataclasses
import functools
import math
import os
import time
import uuid
import weakref
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets
from fsspec.core import url_to_fs

from jupyter_storage_explorer import (
    _infos,
    _jupyterlab_files,
    _paths,
    _static,
    properties,
)
from jupyter_storage_explorer._urls import default_location, default_url
from jupyter_storage_explorer.data_explorer import DataExplorer
from jupyter_storage_explorer.file_tasks import FileTasks, Plan, Task
from jupyter_storage_explorer.filesystems import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
)
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
    OperationChain,
    Progress,
    same_filesystem,
)
from jupyter_storage_explorer.query import DataQuery
from jupyter_storage_explorer.states import ExplorerStates, explorer_states
from jupyter_storage_explorer.transfer_policy import (
    TransferPolicy,
    computer_url,
    jupyterlab_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import narwhals as nw
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.jobs import Job
    from jupyter_storage_explorer.operations import FileSystemOperations

# JavaScript libraries the frontend may ask for (see static/vendor/README.md);
# only these names are served.
_VENDOR_FILES = frozenset({"marked.esm.js", "purify.es.mjs"})

# Largest file that can be downloaded: it passes through kernel memory and the
# notebook's connection in one message.
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

# While a job runs, what it has changed is shown at most this often (seconds):
# items gone leave the list at once, without asking the storage; new items
# show by listing their folder again, a request (for large folders on object
# stores, several), so less often.
_FOLLOW_INTERVAL = 1.0
_RELIST_INTERVAL = 3.0

# The explorers in this kernel, by _explorer_id: files copied in one of them
# are pasted from its own filesystem object (with its credentials), not
# found again from their URLs. Explorers in other kernels are not here.
_explorers: weakref.WeakValueDictionary[str, StorageExplorer] = (
    weakref.WeakValueDictionary()
)


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


def _within_top(path: str, root: str) -> bool:
    """Whether ``path`` is in top folder ``root`` (any relative path when
    the root is "", as for DirFileSystems), without ".." parts."""
    if ".." in path.split("/"):
        return False
    return root == "" or _paths.inside(path, root)


@dataclasses.dataclass
class _Followed:
    """How much of a running task's changes the explorer has shown (see
    ``StorageExplorer._follow``): counts of its records shown, and when."""

    moved: int = 0
    removed: int = 0
    moved_away: int = 0
    additions: int = 0
    shown_at: float = -math.inf
    listed_at: float = -math.inf


def _error_text(exc: Exception) -> str:
    """An error for users: the explorer's own refusals (ValueError) as they
    are, others with their type, e.g. "FileNotFoundError: ..."."""
    return str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"


def _entry(info: dict[str, Any]) -> dict[str, Any]:
    is_dir = info.get("type") == "directory"
    return {
        "name": _paths.basename(info["name"]),
        "path": _paths.norm(info["name"]),
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else info.get("size"),
        "mtime": _infos.mtime(info),
    }


def _section(preview: Preview) -> dict[str, Any]:
    """A preview section as JSON for the frontend; media bytes are base64-encoded."""
    data = {f.name: getattr(preview, f.name) for f in dataclasses.fields(preview)}
    if isinstance(preview, MediaPreview) and preview.data is not None:
        data["data"] = base64.b64encode(preview.data).decode("ascii")
    return {"kind": preview.kind, **jsonable(data)}


class StorageExplorer(anywidget.AnyWidget):
    """Browse any fsspec-supported storage with a directory tree and a file list.

    Double-clicking a file (or Preview) opens a preview below the list;
    tables open in a data browser ("Query data"). The right-click menu offers
    "Python code" to load the data, "Edit" for text files, downloads, "Copy",
    "Cut" and "Paste" (also between storages and explorers, in this notebook
    or others), "Delete" and "Create a folder".
    Files dragged from JupyterLab's file browser or the user's computer are
    uploaded; files dragged onto a folder are moved there. Folders are moved,
    copied and deleted only in "Unsafe mode" (the slider in the toolbar),
    which any operation turns off again.

    Moving, deleting, pasting, uploading and downloading to JupyterLab run in
    the background, one at a time, with their progress and a Cancel button;
    the explorer stays usable meanwhile.

    Parameters
    ----------
    path : str, optional
        Where to start: a URL or path fsspec understands, e.g.
        ``"s3://my-bucket/data"``; with ``fs``, a path within that filesystem.
        Default: the current folder (or the top of ``fs``).
    fs : AbstractFileSystem, optional
        An existing fsspec filesystem to browse, instead of one made from
        ``path`` and ``storage_options``.
    filesystems : mapping of str to AbstractFileSystem or str, optional
        Several storages, by name, chosen with a drop-down in the widget; each
        remembers its folder while another is shown. Values are filesystems
        (starting at their top level; wrap one in fsspec's ``DirFileSystem``
        to start in a subfolder) or URLs (starting at that path). Cannot be
        combined with ``path``, ``fs`` or storage options.
    height : str, default "400px"
        Height of the tree and the list (CSS); the preview panel adds its own.
        ``"fill"``: as tall as the container, e.g. the launcher's tab (not a
        notebook cell, which has no height of its own).
    formats : sequence of DataFormat, optional
        The formats files are previewed and queried as, replacing
        ``default_formats()``. Cannot be combined with ``format_options``.
    format_options : mapping, optional
        Keyword arguments to create every default format with, each using
        those it takes, e.g. ``{"polars_storage_options": {...}}`` (see
        "Format options" in docs/storage-explorer.md).
    preview_limits : PreviewLimits, optional
        How much of a file previews read and show (bytes, rows).
    max_upload_bytes : int or None, default 10 MB
        Largest file uploaded from the user's computer; None for no limit.
        Files dragged from JupyterLab's file browser are not limited.
    download_to_jupyterlab_path : str, default "."
        The folder "Download to JupyterLab" copies into, on the kernel's
        machine, e.g. ``"~/Downloads"``; relative paths and "~" are resolved
        when the explorer is created. To refuse downloads, use ``transfer_policy``
        (to ``"jupyterlab://.*"`` or ``"browser:///.*"``).
    states : ExplorerStates, str or Path, optional
        Where the bookmarks and the data browser's recent queries are kept:
        an ``ExplorerStates``, or the path of its JSON file, e.g.
        ``"~/.jupyter/storage-explorer/states.json"`` (explorers given the
        same file share one). Default: one shared by the explorers in the
        kernel, in memory. A file is read again when the explorer is created.
    max_browser_items : int or None, default 20_000
        Folders with more items are filtered, sorted and paged by the kernel
        (see ``listing.Listing``), one page at a time, instead of by the
        browser from the whole listing; None for never.
    fetch_rows : callable, optional
        Reads one page of a live query's result in the data browser, as
        ``fetch_rows(lf, offset, length)``, e.g. to skip rows in a library
        the default reads them all for; None to leave the page to the
        default, ``jupyter_storage_explorer.fetch_rows``, which has an
        example.
    operations : sequence of FileSystemOperations, optional
        File operations of your own, tried before ``default_operations()``,
        e.g. ``[MyOps()]`` for server-side copies: for each operation (move,
        copy, delete, ...), the first object that supports it does it (see
        operations.py). To change the defaults themselves, override
        ``default_operations`` in a subclass.
    transfer_policy : list of dict, optional
        Rules for the directions files may be transferred in, each
        ``{"rule": "allow" or "deny", "src": regex, "dest": regex}``.
        Transfers are copies and moves between filesystems: copy (or cut)
        and paste between storages, and transfers with JupyterLab's file
        browser (``jupyterlab://<absolute path>``, "Download to JupyterLab"
        too) and the user's computer (``browser:///<name>``); not those
        within a filesystem, e.g. dragging files onto a folder. The first
        rule whose patterns both match the whole source and destination URLs
        (``re.fullmatch``; a pattern left out matches any) decides; without
        one, files go. Items refused are reported, the others done. Not a
        security boundary: it only keeps files from going where they are not
        meant to by mistake (see transfer_policy.py).
    **storage_options
        Passed to fsspec with ``path``, e.g. ``anon=True`` or
        ``profile="analytics"``.

    Raises
    ------
    TypeError
        If ``filesystems`` is combined with ``path``, ``fs`` or storage
        options, or storage options with ``fs``.
    ValueError
        If ``filesystems`` is empty, or ``transfer_policy`` has a rule that is not
        of that form.

    See Also
    --------
    DataExplorer : The data browser alone, for a dataframe.

    Notes
    -----
    ``folder_url`` and ``selected_urls`` give the locations of the folder
    shown and of the selected items. To change how paths become locations
    ("Copy URL", these properties, "Python code", data read by polars),
    override ``_url`` in a subclass.

    Examples
    --------
    >>> StorageExplorer()  # the current folder
    >>> StorageExplorer("s3://my-bucket/data", anon=True)
    >>> StorageExplorer("data", fs=my_filesystem)
    >>> StorageExplorer(filesystems={"Lake": s3, "Local": "file:///home/me/data"})
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
    # Formats of text files (Text and its subclasses, e.g. code, logs, Markdown),
    # which JupyterLab's text editor opens even when it does not know the
    # file's type ("Open in JupyterLab", double-click).
    _text_formats = traitlets.List().tag(sync=True)
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
    # The "Unsafe mode" switch in the toolbar: while on, risky operations
    # are offered (today: moving, copying, pasting, renaming and deleting folders). The
    # frontend turns it off when any operation starts, and sends with each
    # request whether it was on ("unsafe").
    _unsafe_mode = traitlets.Bool(False).tag(sync=True)
    # Identifies this explorer to "Paste" (see _paste_sources), and to the
    # page-wide "changed" events after its files were cut and pasted elsewhere.
    _explorer_id = traitlets.Unicode().tag(sync=True)
    # Absolute folder on the kernel's machine "Download to JupyterLab" copies into.
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
        download_to_jupyterlab_path: str = ".",
        states: ExplorerStates | str | os.PathLike[str] | None = None,
        max_browser_items: int | None = 20_000,
        fetch_rows: Callable[[nw.LazyFrame, int, int], nw.DataFrame | None]
        | None = None,
        operations: Sequence[FileSystemOperations] | None = None,
        transfer_policy: Sequence[Mapping[str, str]] | None = None,
        **storage_options: Any,
    ) -> None:
        self._transfer_policy = TransferPolicy(transfer_policy)
        self._fetch_rows = fetch_rows
        self._states = explorer_states(states)
        # Its file may have been changed by another kernel since it was read.
        try:
            self._states.reload()
            states_error = ""
        except (OSError, ValueError) as exc:
            states_error = f"Bookmarks and queries not read again: {exc}"
        self._max_browser_items = max_browser_items
        # How files are moved, copied, deleted and downloaded (see operations.py),
        # and the jobs doing it in the background (see jobs.py).
        self._operations = OperationChain(
            [*(operations or ()), *self.default_operations()]
        )
        self._jobs = JobRunner(self._send_job)
        # "Properties" counts files with jobs of its own: it changes nothing,
        # so it need not wait for a move or a copy to end.
        self._scans = JobRunner(self._send_job, prefix="scan")
        # The current directory's items, kept for "list" requests (and paths).
        self._full_listing = Listing(self._make_listing("", []))
        self._listing_version = 0
        # Data browser: path -> the data being queried.
        self._queries: dict[str, DataQuery] = {}
        # Data browsers in tabs of their own ("query_tab"): model id -> widget,
        # kept here while the tab is open.
        self._query_tabs: dict[str, DataExplorer] = {}
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
            _text_formats=[f.name for f in self._formats if isinstance(f, Text)],
            _max_upload_bytes=max_upload_bytes,
            _filesystem_names=list(self._filesystems),
            _explorer_id=uuid.uuid4().hex,
            # Resolved now: "." is the folder the explorer is launched in,
            # even if the kernel's working directory changes later.
            _download_to_jupyterlab_path=os.path.abspath(
                os.path.expanduser(download_to_jupyterlab_path)
            ),
        )
        self.on_msg(self._on_custom_msg)
        _explorers[self._explorer_id] = self
        self._filesystem = name  # shows its top level (see _on_filesystem)
        if states_error:
            self._error = states_error

    @staticmethod
    def default_operations() -> list[FileSystemOperations]:
        """The file operations tried after those given as ``operations``.

        Returns
        -------
        list of FileSystemOperations
            New objects each time: ``AtomicMoveOperation`` (moves in one step
            on local disks), ``AsyncFsspecOperations`` (asynchronous fsspec
            filesystems such as s3fs, gcsfs and adlfs, many files at a time),
            then ``FsspecOperations`` (everything else, with fsspec), from the
            ``jupyter_storage_explorer.filesystems`` package. The last does
            every operation, so the explorer can always do them.
        """
        return [AtomicMoveOperation(), AsyncFsspecOperations(), FsspecOperations()]

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

    def _restore_view(self, filesystem: Any, folders: Any) -> None:
        """Show storage ``filesystem`` at its folder in ``folders`` ({storage
        name: folder}), and remember the others' for when they are shown: a
        view saved by the launcher's tab, to reopen where it was.

        Saved views may be stale or edited: storages no longer offered,
        folders outside a storage's top folder and values of the wrong type
        are ignored, and a folder that is gone gives the top folder (see
        ``_on_filesystem``).
        """
        folders = folders if isinstance(folders, dict) else {}
        wanted = {
            name: folder
            for name, folder in folders.items()
            if name in self._filesystems
            and isinstance(folder, str)
            and _within_top(folder, self._filesystems[name][1])
        }
        if filesystem not in self._filesystems:
            filesystem = self._filesystem
        if filesystem != self._filesystem:
            if filesystem in wanted:
                self._remembered[filesystem] = wanted[filesystem]
            self._filesystem = filesystem  # shows its remembered folder
        elif filesystem in wanted and self._exists_folder(wanted[filesystem]):
            self._current_dir = wanted[filesystem]
        # Set last: switching remembers the folder left (the top one).
        self._remembered.update(
            {name: f for name, f in wanted.items() if name != self._filesystem}
        )

    def _exists_folder(self, path: str) -> bool:
        try:
            return self._isdir(path)
        except Exception:
            return False  # cannot tell: stay at the top

    # --- Public interface ---

    @property
    def folder_url(self) -> str | None:
        """The location of the folder shown in the list (see ``_url``).

        Returns
        -------
        str or None
            A URL (or a plain path for local files) usable with
            ``fsspec.open``, polars, pandas, etc.; None if it has none.
        """
        return self._url(self._current_dir)

    @property
    def selected_urls(self) -> list[str]:
        """The locations of the selected items (see ``_url``).

        Returns
        -------
        list of str
            Their URLs, in the order selected. Items without one are left out,
            so the list is empty when nothing with a URL is selected.
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
            "jupyterlab_get": lambda c, _: self._reply(c, self._jupyterlab_get(c)),
            "jupyterlab_save": lambda c, _: self._reply(c, self._jupyterlab_save(c)),
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
            "rename": lambda c, _: self._reply(c, self._rename_request(c)),
            "download_to_server": lambda c, _: self._reply(
                c, self._download_to_server_request(c)
            ),
            "delete": lambda c, _: self._reply(c, self._delete_request(c)),
            "paste": lambda c, _: self._reply(c, self._paste_request(c)),
            # Files cut here were pasted in another explorer (told by its frontend).
            "changed": lambda c, _: self._sources_changed(c["filesystem"], c["paths"]),
            "create_folder": lambda c, _: self._reply(
                c, self._create_folder_request(c)
            ),
            "download_to_jupyterlab": lambda c, _: self._reply(
                c, self._download_to_jupyterlab_request(c)
            ),
            "properties": lambda c, _: self._reply(c, self._properties_request(c)),
            "query_rows": lambda c, _: self._reply(c, self._query_request(c)),
            "query_check": lambda c, _: self._reply(c, self._query_request(c)),
            "query_save": lambda c, _: self._reply(c, self._query_request(c)),
            "query_reload": lambda c, _: self._reply(c, self._query_request(c)),
            "query_mode": lambda c, _: self._reply(c, self._query_request(c)),
            "query_tab": lambda c, _: self._reply(c, self._query_tab_request(c)),
            "query_tab_closed": lambda c, _: self._query_tab_closed(c["model_id"]),
            "bookmarks": lambda c, _: self._reply(c, self._bookmark_list()),
            "bookmark_add": lambda c, _: self._reply(c, self._add_bookmark(c["path"])),
            "bookmark_remove": lambda c, _: self._reply(
                c, self._remove_bookmark(c["filesystem"], c["path"])
            ),
            "bookmark_open": lambda c, _: self._reply(
                c, self._open_bookmark(c["filesystem"], c["path"])
            ),
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
        "sizes" (None for folders), "mtimes" and "ctimes" (modification and
        creation times, for tooltips: whole seconds, or None), and
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
            "ctimes": [],
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
            ctime = _infos.ctime(info)
            listing["ctimes"].append(None if ctime is None else int(ctime))
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

    # --- Locations: how paths become URLs and back (override _url and
    # _locate to change them) ---

    def _url(self, path: str) -> str | None:
        """The location of a path of the filesystem shown, for users and libraries.

        The one place paths become locations: "Copy URL", ``folder_url``,
        "Python code" snippets and previews that read by location all use it.
        Override it in a subclass, e.g. to resolve a ``DirFileSystem`` to its
        underlying location; with several ``filesystems``, tell them apart by
        ``self._filesystem``.

        Parameters
        ----------
        path : str
            A file or folder of the filesystem shown (``self._fs``), as fsspec
            lists it.

        Returns
        -------
        str or None
            A plain path for local files, which every library reads;
            ``abfs://container@account.dfs.core.windows.net/key`` for Azure
            (adlfs), which names the account; ``protocol://path`` otherwise.
            An override may return None for items without a URL: they can
            still be browsed, uploaded to, downloaded and moved, but have no
            "Copy URL", preview, "Query data", "Python code" or "Edit".

        See Also
        --------
        _locate : The reverse, override it along with this method.
        """
        return default_url(self._fs, path)

    def _locate(self, url: str) -> tuple[AbstractFileSystem, str]:
        """The filesystem and path of a location: the reverse of ``_url``.

        Used to paste files copied in an explorer of another kernel (another
        notebook), which only says where they are by their URLs; those copied
        in this kernel are read from their explorer's filesystem directly.
        Override it with ``_url``, so that what one makes the other reads.

        Parameters
        ----------
        url : str
            A location made by ``_url``, in this explorer or another one.

        Returns
        -------
        tuple of (AbstractFileSystem, str)
            The filesystem and its fsspec path. One of this explorer's
            filesystems if one has the URL's protocol (the one shown first;
            for Azure, one of the URL's account), so with its credentials;
            else one fsspec opens from the URL, with the environment's.

        Raises
        ------
        ValueError
            If the URL does not tell which storage it is on, e.g.
            ``abfs://container/key`` (without the account).
        """
        others = [fs for fs, _ in self._filesystems.values() if fs is not self._fs]
        return default_location(url, [self._fs, *others])

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
        data = self._new_query(fmt, target)
        self._queries[path] = data
        return data.opening()

    def _new_query(self, fmt: DataFormat, target: Target) -> DataQuery:
        """The data browser's query of ``target`` read as ``fmt``.

        Settings are remembered by URL, so they follow the data across
        explorers and tabs, with the mode last chosen for it.
        """
        scan = functools.partial(fmt.scan, target.url, target.is_dir)
        state = self._states.query(target.url)
        mode = state.mode if state is not None else "auto"
        fetch = self._fetch_rows
        try:
            return DataQuery(scan, target.url, self._states, mode=mode, fetch=fetch)
        except ValueError:
            if mode != "live":
                raise
            # "live" chosen when the format scanned lazily, and no longer does.
            return DataQuery(scan, target.url, self._states, fetch=fetch)

    # --- Query data in a new tab: a DataExplorer of the same query, which the
    # launcher's JupyterLab extension shows in a tab of its own ---

    def _query_tab_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "query_tab": open ``path`` (as ``format``, else its best
        format) in a new ``DataExplorer``, kept until the tab closes
        ("query_tab_closed"). {"model_id", "title", "url"} or {"error"}."""
        path = content.get("path")
        try:
            target, formats = self._detect(path)
            if target is None:
                raise ValueError(f"{path} has no URL, so it cannot be queried")
            if content.get("format"):
                formats = [f for f in formats if f.name == content["format"]]
            if not formats or not formats[0].can_query():
                raise ValueError(f"{_paths.basename(path)} cannot be queried")
            explorer = DataExplorer._of_query(
                self._new_query(formats[0], target),
                self._states,
                target.url,
                title=_paths.basename(path),
                height="fill",
            )
        except Exception as exc:
            return {"error": _error_text(exc)}
        self._query_tabs[explorer.model_id] = explorer
        return {
            "model_id": explorer.model_id,
            "title": _paths.basename(path),
            "url": target.url,
        }

    def _query_tab_closed(self, model_id: str) -> None:
        """The tab of a "query_tab" closed: its DataExplorer is no longer kept."""
        explorer = self._query_tabs.pop(model_id, None)
        if explorer is not None:
            explorer.close()

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
        """Answer the right-click menu's request: matching formats ("Preview as")
        and load code ("Python code")."""
        reply: dict[str, Any] = {"type": "menu_info", "path": path}
        try:
            target, formats = self._detect(path)
            reply["formats"] = [f.name for f in formats]
            reply["recipes"] = (
                [dataclasses.asdict(r) for r in formats[0].recipes(target)]
                if formats
                else []
            )
            reply["query"] = bool(formats) and formats[0].can_query()
        except Exception as exc:
            reply["error"] = f"{type(exc).__name__}: {exc}"
        self.send(reply)

    # --- Bookmarks: folders, kept in the explorer states (states.py), so
    # shared with the explorers using the same states ---

    def _bookmark_list(self) -> dict[str, Any]:
        """{"bookmarks": [{"filesystem", "path", "url", "label"}]}: those of this
        explorer's storages, within their top folders, labelled "[storage]
        path" and in alphabetical order of storage, then path (ignoring case)."""
        bookmarks = [
            {
                "filesystem": b.filesystem,
                "path": b.path,
                "url": b.url,
                "label": f"[{b.filesystem}] {b.path}",
            }
            for b in self._states.bookmarks
            if b.filesystem in self._filesystems
            and _within_top(b.path, self._filesystems[b.filesystem][1])
        ]
        bookmarks.sort(key=lambda b: (b["filesystem"].casefold(), b["path"].casefold()))
        return {"bookmarks": bookmarks}

    def _add_bookmark(self, path: str) -> dict[str, Any]:
        """Bookmark folder ``path`` of the storage shown; the bookmarks, or {"error"}."""
        if not _within_top(path, self._root) or not self._exists_folder(path):
            return {"error": f"{path} is not a folder of this storage"}
        self._states.add_bookmark(self._filesystem, path, self._url(path))
        return self._bookmark_list()

    def _remove_bookmark(self, filesystem: str, path: str) -> dict[str, Any]:
        self._states.remove_bookmark(filesystem, path)
        return self._bookmark_list()

    def _open_bookmark(self, filesystem: str, path: str) -> dict[str, Any]:
        """Show bookmarked folder ``path`` of storage ``filesystem``: {} or {"error"}."""
        storage = self._filesystems.get(filesystem)
        if storage is None or not _within_top(path, storage[1]):
            return {"error": f"{path} is not in this explorer's storages"}
        try:
            exists = self._isdir(path, storage[0])
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        if not exists:
            return {"error": f"{path} no longer exists"}
        if filesystem == self._filesystem:
            self._current_dir = path
        else:
            self._remembered[filesystem] = path
            self._filesystem = filesystem  # shows the folder remembered
        return {}

    # --- Open in JupyterLab: its own editors and viewers, through the launcher's drive ---

    def _jupyterlab_file(
        self, content: dict[str, Any]
    ) -> tuple[AbstractFileSystem, str]:
        """The storage and path of a file opened in JupyterLab: by the storage's
        name, as the file may stay open there while another storage is shown."""
        storage = self._filesystems.get(content.get("filesystem"))
        path = content.get("path")
        if (
            storage is None
            or not isinstance(path, str)
            or not _within_top(path, storage[1])
        ):
            raise ValueError("not a file of this explorer's storages")
        return storage[0], path

    def _jupyterlab_get(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "jupyterlab_get": {"model": the file's contents model} (see
        _jupyterlab_files.contents_model), or {"error"}."""
        try:
            fs, path = self._jupyterlab_file(content)
            info = self._info(path, fs)
            if info.get("type") == "directory":
                raise ValueError("folders cannot be opened in JupyterLab")
            size = info.get("size")
            if size is not None and size > _jupyterlab_files.MAX_BYTES:
                raise ValueError(
                    f"too large to open in JupyterLab "
                    f"(over {_jupyterlab_files.MAX_BYTES // (1024 * 1024)} MB)"
                )
            data = self._read_bytes(path, fs)
            model = _jupyterlab_files.contents_model(
                path,
                data,
                info,
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=content.get("content", True),
            )
        except Exception as exc:
            return {"error": _error_text(exc)}
        return {"model": model}

    def _jupyterlab_save(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "jupyterlab_save": write the content JupyterLab saves to the
        file; {"model": its contents model, without content} or {"error"}.

        JupyterLab itself checks, with the hash, that the file has not been
        changed elsewhere since it was opened, before saving.
        """
        try:
            fs, path = self._jupyterlab_file(content)
            current = self._read_bytes(path, fs) if self._exists(path, fs) else None
            data = _jupyterlab_files.saved_bytes(
                content.get("content"), content.get("format"), current
            )
            self._write_bytes(path, data, fs)
            model = _jupyterlab_files.contents_model(
                path,
                data,
                self._info(path, fs),
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=False,
            )
        except Exception as exc:
            return {"error": _error_text(exc)}
        if content.get("filesystem") == self._filesystem:
            self._update_entry(path)
            if self._preview.get("path") == path:
                self._open_preview(path, self._preview.get("format"))
        return {"model": model}

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
                refused = self._transfer_policy.error(
                    self._location(self._fs, path),
                    computer_url(_paths.basename(path)),
                )
                if refused is not None:
                    raise PermissionError(refused)
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
    # in a job's worker thread (jobs.py), and back on the main thread, _follow
    # shows what it has changed so far as it runs, and _finish all it changed
    # once it has ended ---

    def _tasks(self, urls: Mapping[tuple[int, str], str] | None = None) -> FileTasks:
        """Plans operations on the filesystem shown, within the policy.

        ``urls``: the URLs of files pasted, as copied, by (id of their
        filesystem, normalized path), for the policy (see ``_transfer_error``).
        """
        return FileTasks(
            self._fs,
            self._root,
            self._operations,
            check=functools.partial(self._transfer_error, urls=urls or {}),
        )

    def _transfer_error(
        self,
        source_fs: AbstractFileSystem | None,
        source: str,
        target_fs: AbstractFileSystem | None,
        target: str,
        urls: Mapping[tuple[int, str], str],
    ) -> str | None:
        """Why the policy refuses copying or moving ``source`` to ``target``, or
        None. A filesystem None is JupyterLab's side (see ``FileTasks``)."""
        if not self._transfer_policy.rules:
            return None
        source_url = urls.get((id(source_fs), _paths.norm(source)))
        if source_url is None:
            source_url = self._location(source_fs, source)
        return self._transfer_policy.error(
            source_url, self._location(target_fs, target)
        )

    def _location(self, fs: AbstractFileSystem | None, path: str) -> str:
        """``path``'s URL for the policy: ``_url``'s on the filesystem shown,
        else (another storage, files without a URL) ``default_url``'s; for
        fs None, the Jupyter server's disk through JupyterLab's file browser,
        ``jupyterlab_url``'s."""
        if fs is None:
            return jupyterlab_url(path)
        if same_filesystem(fs, self._fs) and (url := self._url(path)) is not None:
            return url
        return default_url(fs, path)

    def _start(self, plan: Plan) -> dict[str, Any]:
        """Run ``plan`` as a job: {"job": its id}; or the reply as it is if
        there is nothing to run (e.g. {"conflicts": [...]} to ask about)."""
        if isinstance(plan, dict):
            return plan
        followed = _Followed()
        job = self._jobs.submit(
            plan.kind,
            plan.title,
            plan.work,
            finish=lambda job: self._finish(plan),
            update=lambda job: self._follow(plan, followed),
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
        for fs, path in task.moved_away:
            self._moved_away(fs, path)
        if not same_filesystem(task.fs, self._fs):
            task.fs.invalidate_cache()  # the user has switched filesystems
            return
        for source, target in task.moved:
            self._forget(source, moved_to=target)
        for path in task.removed:
            self._forget(path)
        for folder in task.changed:
            self._refresh_dir(folder)

    def _follow(self, task: Task, followed: _Followed) -> None:
        """While ``task`` runs, show what it has changed since last time
        (``followed``): items moved or deleted leave the list and the tree at
        once (they are only dropped, so this asks the storage nothing);
        folders that got new items are listed again, less often (see
        ``_FOLLOW_INTERVAL``, ``_RELIST_INTERVAL``). ``_finish`` shows
        everything once it has ended."""
        now = time.monotonic()
        if now - followed.shown_at < _FOLLOW_INTERVAL:
            return
        followed.shown_at = now
        changes = task.changes()
        shown = same_filesystem(task.fs, self._fs)  # else the user switched
        gone: list[tuple[str, str | None]] = []
        for fs, path in changes.moved_away[followed.moved_away :]:
            if same_filesystem(fs, self._fs):
                gone.append((path, None))
            else:
                fs.invalidate_cache(_paths.parent(path, fs))
        if shown:
            gone += changes.moved[followed.moved :]
            gone += [(path, None) for path in changes.removed[followed.removed :]]
        followed.moved_away = len(changes.moved_away)
        followed.moved = len(changes.moved)
        followed.removed = len(changes.removed)
        if gone:
            self._show_gone(gone)
        if (
            shown
            and changes.additions > followed.additions
            and now - followed.listed_at >= _RELIST_INTERVAL
        ):
            followed.additions = changes.additions
            followed.listed_at = now
            for folder in changes.added_to:
                self._invalidate_cache(folder)
                if folder == self._current_dir:
                    self._relist_current()
                elif folder in self._tree:
                    self._load_children(folder)

    def _show_gone(self, gone: Sequence[tuple[str, str | None]]) -> None:
        """Drop items moved (to the path paired with them) or deleted (None)
        from the list, the selection and the tree, without listing again."""
        for path, moved_to in gone:
            self._invalidate_cache(_paths.parent(path, self._fs))
            self._forget(path, moved_to=moved_to)  # e.g. leaves a folder deleted
        paths = {_paths.norm(path) for path, _ in gone}
        rows = {
            i for i, p in enumerate(self._listed_paths()) if _paths.norm(p) in paths
        }
        if rows:
            self._full_listing = self._full_listing.without(rows)
            self._send_listing()
        if any(_paths.norm(p) in paths for p in self._selected):
            self._selected = [p for p in self._selected if _paths.norm(p) not in paths]
        tree = {
            folder: [d for d in dirs if _paths.norm(d["path"]) not in paths]
            for folder, dirs in self._tree.items()
        }
        if tree != self._tree:
            self._tree = tree

    def _relist_current(self) -> None:
        """List the folder shown again, keeping the selection (unlike _list,
        for a folder newly shown): items appear while a job adds them."""
        path = self._current_dir
        try:
            infos = self._ls(path)
        except Exception:
            return  # the job's end lists it again, and reports errors
        self._set_children(path, infos)
        self._show_listing(self._make_listing(path, infos))
        listed = {_paths.norm(p) for p in self._listed_paths()}
        kept = [p for p in self._selected if _paths.norm(p) in listed]
        if kept != list(self._selected):
            self._selected = kept

    def _moved_away(self, fs: AbstractFileSystem, path: str) -> None:
        """Follow ``path`` of ``fs``, cut and pasted into another filesystem.

        If ``fs`` is shown, as if deleted; else (another of this explorer's
        storages, or another explorer's, whose frontend tells it: see
        ``_sources_changed``) its cached listing is dropped.
        """
        parent = _paths.parent(path, fs)
        if not same_filesystem(fs, self._fs):
            fs.invalidate_cache(parent)
            return
        self._forget(path)
        self._refresh_dir(parent)

    def _sources_changed(self, filesystem: str, paths: Sequence[str]) -> None:
        """Answer "changed": files of storage ``filesystem`` were cut here and
        pasted in another explorer, which may have moved some (or all) away."""
        entry = self._filesystems.get(filesystem)
        if entry is None:
            return
        fs = entry[0]
        parents = {_paths.parent(p, fs) for p in paths}
        if fs is not self._fs:
            for parent in parents:
                fs.invalidate_cache(parent)
            return
        for parent in parents:
            self._invalidate_cache(parent)
        for path in paths:
            if not self._exists(path):
                self._forget(path)
        for parent in parents:
            self._refresh_dir(parent)

    def _send_job(self, job: Job) -> None:
        """Tell the frontend how ``job`` is doing (see Job.snapshot)."""
        self.send({"type": "job", **job.snapshot()})

    def _cancel_job(self, content: dict[str, Any]) -> None:
        job_id = content.get("id", "")
        if not self._jobs.cancel(job_id):
            self._scans.cancel(job_id)

    def _plan_request(self, plan: Callable[[], Plan]) -> dict[str, Any]:
        """Answer a request for an operation: start ``plan()``, or say why not."""
        try:
            return self._start(plan())
        except Exception as exc:
            return {"errors": [f"{type(exc).__name__}: {exc}"]}

    # --- Move: files (and, in unsafe mode, folders) dragged onto a folder;
    # rename and delete: chosen in the right-click menu ---

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

    def _rename_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().rename(
                content["path"], content["name"], folders=bool(content.get("unsafe"))
            )
        )

    def _rename(self, path: str, name: str, folders: bool = False) -> dict[str, Any]:
        """Rename an item, now (see ``FileTasks.rename``)."""
        return self._run_now(self._tasks().rename(path, name, folders))

    def _delete_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().delete(
                content["paths"], folders=bool(content.get("unsafe"))
            )
        )

    def _delete(self, paths: Sequence[str], folders: bool = False) -> dict[str, Any]:
        """Delete files, now (see ``FileTasks.delete``)."""
        return self._run_now(self._tasks().delete(paths, folders))

    # --- Paste: files (and, in unsafe mode, folders) copied with "Copy" or
    # "Cut" (in any explorer, any storage), into a folder ---

    def _paste_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "paste": files copied (or with "cut", cut) in the explorer
        ``content["explorer"]``, from its storage ``content["filesystem"]``."""
        return self._plan_request(
            lambda: self._paste_plan(
                content["files"],
                content["dest"],
                content.get("if_exists", "ask"),
                explorer=content.get("explorer"),
                filesystem=content.get("filesystem"),
                folders=bool(content.get("unsafe")),
                cut=bool(content.get("cut")),
            )
        )

    def _paste(
        self,
        files: Sequence[dict[str, Any]],
        dest: str,
        if_exists: str = "ask",
        *,
        explorer: str | None = None,
        filesystem: str | None = None,
        folders: bool = False,
        cut: bool = False,
    ) -> dict[str, Any]:
        """Paste files into folder ``dest``, now (see ``_paste_plan``)."""
        return self._run_now(
            self._paste_plan(
                files,
                dest,
                if_exists,
                explorer=explorer,
                filesystem=filesystem,
                folders=folders,
                cut=cut,
            )
        )

    def _paste_plan(
        self,
        files: Sequence[dict[str, Any]],
        dest: str,
        if_exists: str,
        *,
        explorer: str | None,
        filesystem: str | None,
        folders: bool,
        cut: bool,
    ) -> Plan:
        """Plan pasting ``files`` ({"path", "url"}, as copied) into ``dest``
        (see ``FileTasks.paste``)."""
        sources, errors, urls = self._paste_sources(files, explorer, filesystem, cut)
        return self._tasks(urls).paste(
            sources, dest, if_exists, folders=folders, cut=cut, errors=errors
        )

    def _paste_sources(
        self,
        files: Sequence[dict[str, Any]],
        explorer: str | None,
        filesystem: str | None,
        cut: bool = False,
    ) -> tuple[
        list[tuple[AbstractFileSystem, str]], list[str], dict[tuple[int, str], str]
    ]:
        """The (filesystem, path) of files copied in explorer ``explorer``, from
        its storage ``filesystem``, errors for those not found, and their URLs
        as copied (by their explorer's ``_url``), for the policy (see
        ``_tasks``).

        If that explorer is in this kernel, its filesystem object is used, as
        it is (credentials included). Otherwise it is in another kernel and
        only the files' URLs tell where they are (see ``_locate``).
        """
        source = _explorers.get(explorer or "")
        entry = None if source is None else source._filesystems.get(filesystem or "")
        sources, errors, urls = [], [], {}
        for file in files:
            path, url = file.get("path"), file.get("url")
            try:
                if entry is not None:
                    fs, root = entry
                    if cut and _paths.norm(path) == _paths.norm(root):
                        raise ValueError("the top folder is not moved")
                elif url is None:
                    raise ValueError("its location is unknown")
                else:
                    fs, path = self._locate(url)
            except Exception as exc:
                errors.append(f"{_paths.basename(path or url or '')}: {exc}")
                continue
            sources.append((fs, path))
            if url is not None:
                urls[id(fs), _paths.norm(path)] = url
        return sources, errors, urls

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
            name = _paths.safe_name(content["name"])
            target = _paths.join(content["dest"], name)
            refused = self._transfer_policy.error(
                computer_url(name), self._location(self._fs, target)
            )
            if refused is not None:
                raise PermissionError(refused)
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
        if (error := _paths.name_error(name)) is not None:
            return {"error": error}
        path = _paths.join(dest, name)
        if self._exists(path):
            return {"error": f"{name} already exists"}  # the dialog shows where
        self._operations.mkdir(self._fs, path)
        self._refresh_dir(dest)
        return {"created": name, "hidden": not self._isdir(path)}

    # --- Properties: "Properties" in the right-click menu ---

    def _properties_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "properties": for a single file, {"file": its properties}
        (see ``properties.file_properties``); otherwise {"job": id} of a job
        counting the files and folders (see ``FileTasks.properties``), on the
        runner of its own. Or {"error": reason}."""
        paths = content["paths"]
        try:
            if len(paths) == 1:
                info = self._info(paths[0])
                if info.get("type") != "directory":
                    url = self._url(_paths.norm(info["name"]))
                    return {"file": properties.file_properties(info, url)}
            task = self._tasks().properties(paths)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        job = self._scans.submit(task.kind, task.title, task.work)
        return {"job": job.id}

    # --- Download to the Jupyter server: "Download to JupyterLab", and files
    # dropped on JupyterLab's file browser ---

    def _download_to_jupyterlab_request(
        self, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer "download_to_jupyterlab": copy into ``download_to_jupyterlab_path``."""
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

    def _info(self, path: str, fs: AbstractFileSystem | None = None) -> dict[str, Any]:
        return (fs or self._fs).info(path)

    def _exists(self, path: str, fs: AbstractFileSystem | None = None) -> bool:
        return (fs or self._fs).exists(path)

    def _isdir(self, path: str, fs: AbstractFileSystem | None = None) -> bool:
        """Whether ``path`` is a directory; False if it does not exist (fsspec
        returns False on OSError, e.g. not found or access denied).

        ``fs``: another filesystem than the one shown, e.g. a pasted file's.
        """
        return (fs or self._fs).isdir(path)

    def _read_bytes(self, path: str, fs: AbstractFileSystem | None = None) -> bytes:
        return (fs or self._fs).cat_file(path)

    def _write_bytes(
        self, path: str, data: bytes, fs: AbstractFileSystem | None = None
    ) -> None:
        fs = fs or self._fs
        fs.pipe_file(path, data)
        fs.invalidate_cache(path)

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
