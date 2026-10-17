"""Storage explorer widget: directory tree, file list, and a preview of the selected item."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _paths, _static
from jupyter_storage_explorer._explorer.bookmarks import BookmarksMixin
from jupyter_storage_explorer._explorer.common import (
    explorers,
    open_storage,
    within_top,
)
from jupyter_storage_explorer._explorer.folders import FoldersMixin
from jupyter_storage_explorer._explorer.jobs import JobsMixin
from jupyter_storage_explorer._explorer.jupyterlab import JupyterLabFilesMixin
from jupyter_storage_explorer._explorer.listing import Listing
from jupyter_storage_explorer._explorer.previews import PreviewsMixin
from jupyter_storage_explorer._explorer.requests import FileRequestsMixin
from jupyter_storage_explorer._explorer.states import ExplorerStates, explorer_states
from jupyter_storage_explorer._jobs.incoming import IncomingFiles
from jupyter_storage_explorer._jobs.runner import JobRunner
from jupyter_storage_explorer._jobs.transfer_policy import TransferPolicy
from jupyter_storage_explorer.formats import (
    DataFormat,
    PreviewLimits,
    Text,
    explorer_formats,
)
from jupyter_storage_explorer.fs_mappers.chain import MapperChain
from jupyter_storage_explorer.fs_operations import (
    AsyncFsspecOperations,
    AtomicMoveOperation,
    FsspecOperations,
)
from jupyter_storage_explorer.fs_operations.base import OperationChain

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import narwhals as nw
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer._query.data_query import DataQuery
    from jupyter_storage_explorer.data_explorer import DataExplorer
    from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper
    from jupyter_storage_explorer.fs_operations.base import FileSystemOperations

    # A request's handler: the reply to its content (see _requests).
    _Handler = Callable[[dict[str, Any]], dict[str, Any]]

# JavaScript libraries the frontend may ask for (see static/vendor/README.md);
# only these names are served.
_VENDOR_FILES = frozenset({"marked.esm.js", "purify.es.mjs"})


# Its features are mixins (in _explorer/), each a group of the methods below
# working on the state the class sets up; what the class keeps is that state,
# the messages' routing, the URLs (_url) and the fsspec calls.
class StorageExplorer(
    FoldersMixin,
    PreviewsMixin,
    BookmarksMixin,
    JupyterLabFilesMixin,
    JobsMixin,
    FileRequestsMixin,
    anywidget.AnyWidget,
):
    """Browse any fsspec-supported storage with a directory tree and a file list.

    Preview opens a preview below the list; tables open in a data browser
    ("Query data"). Double-clicking a file opens it in JupyterLab's own
    editors and viewers, with the launcher's extension, else previews it. The
    right-click menu offers "Python code" to load the data, downloads, "Copy",
    "Cut" and "Paste" (also between storages and explorers, in this notebook
    or others), "Rename", "Delete", "Create a folder", "Properties" and
    bookmarks.
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
        ``jupyter_storage_explorer.fs_operations``). To change the defaults themselves, override
        ``default_operations`` in a subclass.
    filesystem_mappers : sequence of FileSystemMapper, optional
        Mappers of your own, tried before
        ``jupyter_storage_explorer.fs_mappers.default_mappers()``: for each
        filesystem, the first that maps it gives the URLs of its paths ("Copy
        URL", ``folder_url``, "Python code", previews, the transfer policy)
        and what it reaches (its identifier), by which files copied or
        dragged from another kernel are found and two filesystems are told
        apart. File operations compare filesystems with the default mappers.
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
        meant to by mistake (see _jobs/transfer_policy.py).
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
    give a mapper in ``filesystem_mappers``.

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
    # The filesystem shown, as its mapper describes it: {"protocol",
    # "identifier"} (see fs_mappers/), sent with files copied or dragged, by
    # which an explorer in another kernel finds them (MapperChain.locate).
    _storage_identity = traitlets.Dict().tag(sync=True)
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
        filesystem_mappers: Sequence[FileSystemMapper] | None = None,
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
        # How files are moved, copied, deleted and downloaded (see fs_operations/),
        # and the jobs doing it in the background (see _jobs/runner.py).
        # What filesystems reach, their URLs and back (see fs_mappers/).
        self._mappers = MapperChain(filesystem_mappers or ())
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
        # Files being received from the user's computer (see _jobs/incoming.py).
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
                name: open_storage(value, None, {})
                if isinstance(value, str)
                else open_storage(None, value, {})
                for name, value in filesystems.items()
            }
        else:
            self._filesystems = {"default": open_storage(path, fs, storage_options)}
        self._remembered: dict[str, str] = {}
        name = next(iter(self._filesystems))
        self._fs: AbstractFileSystem = self._filesystems[name].fs
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
        explorers[self._explorer_id] = self
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
            self._storage_identity = self._mappers.storage_of(self._fs)
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
            and within_top(folder, self._filesystems[name].root)
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
        """Handle a message from the frontend, by its "type": a request, which
        is answered with a "reply" of the same "rid", or a notice, which is
        not (its effects show in the traits, or in messages of their own)."""
        kind = content.get("type")
        if (request := self._requests(buffers or []).get(kind)) is not None:
            self.send({"type": "reply", "rid": content["rid"], **request(content)})
        elif (notice := self._notices().get(kind)) is not None:
            notice(content)

    def _requests(self, buffers: list[Any]) -> dict[str, _Handler]:
        """Request type -> handler(content), giving the reply. ``buffers``: the
        message's binary pieces (a file's piece, for "upload_chunk")."""
        return {
            "menu_info": lambda c: self._menu_info(c["path"]),
            "vendor": lambda c: self._vendor_source(c["name"]),
            # The listing has no URLs (see _make_listing): asked for when copying.
            "urls": lambda c: {"urls": [self._url(p) for p in c["paths"]]},
            "list": self._list_page,
            # The data browser (see DataQuery.handle).
            "query_rows": self._query_request,
            "query_check": self._query_request,
            "query_save": self._query_request,
            "query_reload": self._query_request,
            "query_mode": self._query_request,
            "query_tab": self._query_tab_request,
            # Bookmarks.
            "bookmarks": lambda c: self._bookmark_list(),
            "bookmark_add": lambda c: self._add_bookmark(c["path"]),
            "bookmark_remove": lambda c: self._remove_bookmark(
                c["filesystem"], c["path"]
            ),
            "bookmark_open": lambda c: self._open_bookmark(c["filesystem"], c["path"]),
            # Open in JupyterLab.
            "jupyterlab_get": self._jupyterlab_get,
            "jupyterlab_save": self._jupyterlab_save,
            # File operations: most start a job (see _start).
            "move": self._move_request,
            "rename": self._rename_request,
            "delete": self._delete_request,
            "paste": self._paste_request,
            "create_folder": self._create_folder_request,
            "properties": self._properties_request,
            "upload": self._upload_request,
            "upload_check": lambda c: self._upload_check(c["dest"], c["names"]),
            "upload_chunk": lambda c: self._upload_chunk(c, buffers),
            "download_to_jupyterlab": self._download_to_jupyterlab_request,
            "download_to_server": self._download_to_server_request,
        }

    def _notices(self) -> dict[str, Callable[[dict[str, Any]], None]]:
        """Notice type -> handler(content)."""
        return {
            "expand": lambda c: self._load_children(c["path"]),
            "refresh": lambda c: self._refresh(),
            "preview": lambda c: self._open_preview(c["path"], c.get("format")),
            # Answered with one "download" message per file, its bytes attached.
            "download": lambda c: self._download(c["paths"]),
            "job_cancel": self._cancel_job,
            # Files cut here were pasted in another explorer (told by its frontend).
            "changed": lambda c: self._sources_changed(c["filesystem"], c["paths"]),
            "query_tab_closed": lambda c: self._query_tab_closed(c["model_id"]),
        }

    def _vendor_source(self, name: str) -> dict[str, Any]:
        """Source of a bundled library, e.g. marked for Markdown previews."""
        if name not in _VENDOR_FILES:
            return {"error": f"unknown library {name!r}"}
        return {
            "source": (_static.STATIC / "vendor" / name).read_text(encoding="utf-8")
        }

    # --- The folder shown and the selection, set by the frontend (here, as
    # traitlets' observers must be on the class itself, not on a mixin) ---

    @traitlets.observe("_current_dir")
    def _on_current_dir(self, change: dict[str, Any]) -> None:
        self._list(change["new"])

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

    # --- Locations: the URLs of paths, from the filesystem mappers ---

    def _url(self, path: str) -> str | None:
        """The URL of a path of the filesystem shown (its mapper's ``to_url``),
        or None if it has none."""
        return self._mappers.url_of(self._fs, path)

    # --- File operations: wrappers of fsspec calls on the filesystem shown
    # (``self._fs``) for listing, reading and writing; the methods above go
    # through them, never through fsspec directly. Moving, copying and
    # deleting go through the operations objects instead (see fs_operations/) ---

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

    def _invalidate_cache(self, path: str | None = None) -> None:
        """Forget cached listings (of ``path``, else all), so changes made elsewhere show."""
        self._fs.invalidate_cache(path)
