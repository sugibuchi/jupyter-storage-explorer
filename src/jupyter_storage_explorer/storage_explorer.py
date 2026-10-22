"""Storage explorer widget: directory tree, file list, and a preview of the selected item."""

from __future__ import annotations

import itertools
import os
import uuid
import warnings
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _paths, _static
from jupyter_storage_explorer._callbacks import Callbacks
from jupyter_storage_explorer._explorer.about import AboutMixin
from jupyter_storage_explorer._explorer.bookmarks import BookmarksMixin
from jupyter_storage_explorer._explorer.common import (
    explorers,
    open_storage,
    within_top,
)
from jupyter_storage_explorer._explorer.folders import FoldersMixin
from jupyter_storage_explorer._explorer.icons import format_icons
from jupyter_storage_explorer._explorer.jobs import JobsMixin
from jupyter_storage_explorer._explorer.jupyterlab import JupyterLabFilesMixin
from jupyter_storage_explorer._explorer.listing import Listing
from jupyter_storage_explorer._explorer.previews import PreviewsMixin
from jupyter_storage_explorer._explorer.requests import FileRequestsMixin
from jupyter_storage_explorer._explorer.states import ExplorerStates, explorer_states
from jupyter_storage_explorer._explorer.supports import SupportChain
from jupyter_storage_explorer._jobs.incoming import IncomingFiles
from jupyter_storage_explorer._jobs.loader import Loader
from jupyter_storage_explorer._jobs.operation_chain import OperationChain
from jupyter_storage_explorer._jobs.runner import JobRunner
from jupyter_storage_explorer._jobs.transfer_policy import TransferPolicy
from jupyter_storage_explorer._plugins import PluginComponents, load_plugins
from jupyter_storage_explorer.filesystems import (
    LocalLocation,
    MapperChain,
    default_mappers,
)
from jupyter_storage_explorer.filesystems import (
    default_operations as _default_operations,
)
from jupyter_storage_explorer.filesystems.mapper import protocols
from jupyter_storage_explorer.formats import (
    DataFormat,
    FormatSupport,
    Text,
    ViewLimits,
)
from jupyter_storage_explorer.formats.defaults import DEFAULT_FORMATS, DEFAULT_SUPPORTS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from concurrent.futures import Future

    import narwhals as nw
    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer._explorer.previews import _Detected
    from jupyter_storage_explorer._jobs.loader import Load
    from jupyter_storage_explorer._query.data_query import DataQuery
    from jupyter_storage_explorer._query.table_set import TableSet
    from jupyter_storage_explorer._table_set_tab import TableSetTab
    from jupyter_storage_explorer._view_tab import ViewTab
    from jupyter_storage_explorer.data_explorer import DataExplorer
    from jupyter_storage_explorer.filesystems.mapper import FileSystemMapper
    from jupyter_storage_explorer.filesystems.operation import FileSystemOperations
    from jupyter_storage_explorer.formats import FormatOptions, View
    from jupyter_storage_explorer.location import Location

    # A request's handler: the reply to its content (see _requests).
    _Handler = Callable[[dict[str, Any]], dict[str, Any]]

# The data browser's requests (see DataQuery.handle), and a table set's to
# choose a table (see TableSet), after which query_result() may have changed.
_QUERY_REQUESTS = frozenset(
    {
        "query_rows",
        "query_check",
        "query_save",
        "query_reload",
        "query_mode",
        "table_set_open",
    }
)

# The values of tree_view and preview_panel, and of layout.
_PANEL_STATES = ("open", "closed", "disabled")
_LAYOUTS = ("standard", "sidebar")

# The file list's columns the user can show besides Name (the settings menu's
# Columns), in their order; and those shown by default, per layout.
_LIST_COLUMNS = ("size", "mtime", "ctime", "format")
_DEFAULT_COLUMNS = {"standard": ["size", "mtime"], "sidebar": ["size"]}


def _known_columns(columns: Sequence[str]) -> list[str]:
    """``columns`` that the list has, in its order (a file written by another
    version may name others)."""
    return [c for c in _LIST_COLUMNS if c in columns]


def _check_choice(name: str, value: Any, choices: Sequence[str]) -> None:
    if value not in choices:
        raise ValueError(
            f"{name} must be one of {', '.join(map(repr, choices))}, not {value!r}"
        )


# Its features are mixins (in _explorer/), each a group of the methods below
# working on the state the class sets up; what the class keeps is that state,
# the messages' routing, the URLs (_url) and the fsspec calls.
class StorageExplorer(
    AboutMixin,
    FoldersMixin,
    PreviewsMixin,
    BookmarksMixin,
    JupyterLabFilesMixin,
    JobsMixin,
    FileRequestsMixin,
    anywidget.AnyWidget,
):
    """Browse any fsspec-supported storage with a directory tree and a file list.

    Preview opens a preview below the list; tables open in a data browser. Double-clicking a file opens it in JupyterLab's own
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
    tree_view : {"open", "closed", "disabled"}, default "open"
        The folder tree beside the list: shown, or hidden until the user
        shows it with the toolbar's tree button (which hides it again); or
        "disabled": no tree, nor its button.
    preview_panel : {"open", "closed", "disabled"}, default "closed"
        The preview panel below the list: "open" starts with it open, empty
        until a file is clicked: while it is open, clicking a file previews
        it (tables open in the data browser, see ``query_result``).
        "closed": closed until the user previews something. "disabled": no
        preview panel; items are viewed in new tabs instead, with the
        launcher's extension.
    layout : {"standard", "sidebar"}, default "standard"
        "sidebar": a narrow layout, for JupyterLab's side bar (the
        launcher's side panel): a bar of the storage chooser, bookmarks,
        Refresh and the settings menu (with Unsafe mode, first), a bar of
        Up and the folder's path, the filter, the list (its columns
        Name and, by default, Size), the pager when there are several pages, and the
        status bar.
    open_preview : bool, optional
        Deprecated: ``preview_panel="open"`` instead.
    plugin_options : mapping, optional
        The plugins' options, by key (``StorageExplorerPlugin.key``), e.g.
        ``{"pandas-support": {"enabled": False}, "abfs-support":
        {"concurrency": 16}}``: those of every plugin, ``enabled`` (False:
        not used, nor imported) and ``priority`` (higher first; default the
        lowest, then by key), and the plugin's own (its ``options_model``).
        Every plugin installed is used unless disabled here. A plugin that
        cannot be loaded, or options of one not installed, are left out with
        a warning; an option a plugin does not have is a ValueError. What
        plugins give is used after the ``supports``, ``operations`` and
        ``filesystem_mappers`` given, and before the defaults.
    supports : sequence of FormatSupport classes or objects, optional
        Libraries of your own handling formats' data (previews, the data
        browser, "Python code"), e.g. ``[ParquetByDuckDB]``, tried before
        the plugins' and ``default_supports()``: for each job, the first
        support for the format that is installed does it (see
        ``jupyter_storage_explorer.formats.FormatSupport``). Classes are
        created without arguments. The formats files are detected as are
        those of the supports (their ``format``, one object of each), and
        the standard ones. To change the defaults themselves, override
        ``default_supports`` in a subclass.
    format_options : mapping, optional
        The supports' options, by engine key (``"python"`` for the supports
        without an engine), then format name or ``"*"`` for all formats,
        e.g. ``{"polars": {"*": {"storage_options": {...}}, "delta":
        {"use_pyarrow": True}}}``: each support gets those of its
        engine that its ``options_model`` has (see "Format options" in
        docs/storage-explorer.md). Instead of a dict of options, a function
        of the item's ``Location`` returning one, for options depending on
        where the data is, e.g. ``{"polars": {"*": lambda location:
        {"storage_options": keys[location.account_name]}}}``.
    engine_preference : sequence of str, optional
        The engines' keys (``Engine.key``, e.g. ``["pandas", "polars"]``) in
        the order the engine menu offers them; the first is used until
        the user chooses another (a choice remembered in ``states``). Those
        not installed are left out; the other engines installed follow, by
        key. Default: ``["polars", "pandas"]``, then the others.
    view_limits : ViewLimits, optional
        How much views read and show, in the preview panel and in tabs:
        bytes and rows of a file's beginning, the data browser's page size and
        rows in memory (see `formats.ViewLimits`).
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
        File operations of your own, tried before the plugins' and
        ``default_operations()``,
        e.g. ``[MyOps()]`` for server-side copies: for each operation (move,
        copy, delete, ...), the first object that supports it does it (see
        ``jupyter_storage_explorer.filesystems``). To change the defaults themselves, override
        ``default_operations`` in a subclass.
    filesystem_mappers : sequence of FileSystemMapper, optional
        Mappers of your own, tried before the plugins' and
        ``jupyter_storage_explorer.filesystems.default_mappers()``: for each
        filesystem, the first that maps it gives the locations of its paths
        (``jupyter_storage_explorer.Location``: "Copy URL",
        ``folder_location``, "Python code", previews, the transfer policy),
        by which files copied or dragged from another kernel are found and
        two filesystems are told apart (the storage of their locations), also
        for the file operations (their ``same`` argument).
    transfer_policy : list of dict, optional
        Rules for the directions files may be transferred in, each
        ``{"rule": "allow" or "deny", "src": regex, "dest": regex}``.
        Transfers are all copies and moves of files, within a storage as well
        as between storages: dragging files onto a folder, renaming, copy
        (or cut) and paste, and transfers with JupyterLab's file browser
        (``jupyterlab://<absolute path>``, "Download to JupyterLab" too) and
        the user's computer (``browser:///<name>``). The first rule whose
        patterns both match the whole source and destination URLs
        (``re.fullmatch``; a pattern left out matches any) decides; without
        one, files go. Named groups (``(?P<name>...)``), the same in both
        patterns, must capture the same text in both URLs, e.g. to allow
        transfers within one container only. Items refused are reported, the
        others done. Not a security boundary: it only keeps files from going
        where they are not meant to by mistake (see _jobs/transfer_policy.py).
    **storage_options
        Passed to fsspec with ``path``, e.g. ``anon=True`` or
        ``profile="analytics"``.

    Raises
    ------
    TypeError
        If ``filesystems`` is combined with ``path``, ``fs`` or storage
        options, or storage options with ``fs``.
    ValueError
        If ``filesystems`` is empty, ``transfer_policy`` has a rule that is not
        of that form, or ``tree_view``, ``preview_panel`` or ``layout`` is
        none of its values.

    See Also
    --------
    DataExplorer : The data browser alone, for a dataframe.

    Notes
    -----
    ``folder_location`` and ``selected_locations`` give the locations of the
    folder shown and of the selected items (``folder_url`` and
    ``selected_urls`` their URLs), and ``on_change()`` calls a function when
    they change. ``query_result()`` gives the data the data browser shows in
    the preview panel, with its filters applied, and ``on_query_change()``
    calls a function when that changes. To change how paths become locations
    ("Copy URL", these properties, "Python code", data read by polars), give
    a mapper in ``filesystem_mappers``.

    Examples
    --------
    >>> StorageExplorer()  # the current folder
    >>> StorageExplorer("s3://my-bucket/data", anon=True)
    >>> StorageExplorer("data", fs=my_filesystem)
    >>> StorageExplorer(filesystems={"Lake": s3, "Local": "file:///home/me/data"})
    >>> StorageExplorer("s3://my-bucket/data", preview_panel="open")
    >>> StorageExplorer("s3://my-bucket/data", tree_view="closed")
    """

    _esm = _static.esm("storage_explorer")
    _css = _static.css("storage_explorer")

    _root = traitlets.Unicode().tag(sync=True)
    # Directory path -> list of {"name", "path"} of its subdirectories, with
    # "no_url": true for those without a URL (see _url), and "level" for those
    # with one (see _level_of). A directory that has
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
    # "error", "loading"} ("query" instead of "sections" for the data
    # browser); {"empty": true} when the panel is open with nothing in it
    # (preview_panel="open"); empty when the panel is closed.
    _preview = traitlets.Dict().tag(sync=True)
    # The folder tree: "open", "closed" (the toolbar's tree button shows it;
    # the frontend sets these two) or "disabled" (no tree, nor its button).
    _tree_view = traitlets.Unicode("open").tag(sync=True)
    # "disabled" when the explorer has no preview panel (views open in new
    # tabs); else "open" or "closed", as given (whether the panel is open is
    # _preview).
    _preview_panel = traitlets.Unicode("closed").tag(sync=True)
    # "standard", or "sidebar": the narrow layout of the launcher's side panel.
    _layout = traitlets.Unicode("standard").tag(sync=True)
    # The file list's columns besides Name (keys of _LIST_COLUMNS), set by the
    # settings menu's Columns and remembered by layout in ExplorerStates.
    _columns = traitlets.List(traitlets.Unicode()).tag(sync=True)
    # Format name -> label shown to the user, e.g. {"delta": "Delta Lake table"}.
    _format_labels = traitlets.Dict().tag(sync=True)
    # Formats of text files (Text and its subclasses, e.g. code, logs, Markdown),
    # which JupyterLab's text editor opens even when it does not know the
    # file's type ("Open in JupyterLab", double-click).
    _text_formats = traitlets.List().tag(sync=True)
    # Format name -> the icon of its files (DataFormat.file_icon), for the
    # formats that set one; other files get their extension's (icons.js).
    _format_icons = traitlets.Dict().tag(sync=True)
    # Icon name -> SVG markup, for the formats' icons of their own.
    _file_icon_svgs = traitlets.Dict().tag(sync=True)
    # Format name of the current directory itself (e.g. "delta"), or ""
    # if it cannot be previewed; enables the Preview button when nothing is selected.
    _current_format = traitlets.Unicode().tag(sync=True)
    # Format of the single selected item, for the Preview button's label:
    # {"path", "format"} ("format" is "" if it cannot be previewed); empty
    # unless exactly one item is selected. The path lets the frontend ignore an answer for a
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
    # Whether the filesystem shown is a local disk, whose items have a plain
    # path besides their URL ("Copy path", and what "Copy" puts on the
    # system clipboard: LocalLocation.os_path).
    _local_paths = traitlets.Bool(False).tag(sync=True)
    # The filesystem shown's protocol (its locations', e.g. "abfs"), for CSS
    # (data-fs-protocol); and the level of its top folder (_level_of, e.g.
    # "account"; "" for a plain folder), the tree's root. Other folders'
    # come with the tree's entries and the listing.
    _fs_protocol = traitlets.Unicode().tag(sync=True)
    _root_level = traitlets.Unicode().tag(sync=True)
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
    # The settings file the settings menu's "Edit settings" opens in
    # JupyterLab; "" (no such item) unless the launcher offers it
    # (_offer_settings).
    _settings_path = traitlets.Unicode().tag(sync=True)
    # The engines to choose from in the settings menu, in order:
    # [{"key", "label"}]; and the key of the one chosen ("" if there is none),
    # which previews use. The frontend sets _engine when the user chooses.
    _engines = traitlets.List().tag(sync=True)
    _engine = traitlets.Unicode().tag(sync=True)

    def __init__(
        self,
        path: str | None = None,
        *,
        fs: AbstractFileSystem | None = None,
        filesystems: Mapping[str, AbstractFileSystem | str] | None = None,
        height: str = "400px",
        tree_view: str = "open",
        preview_panel: str = "closed",
        layout: str = "standard",
        open_preview: bool | None = None,
        plugin_options: Mapping[str, Mapping[str, Any]] | None = None,
        supports: Sequence[type[FormatSupport] | FormatSupport] | None = None,
        format_options: FormatOptions | None = None,
        engine_preference: Sequence[str] | None = None,
        view_limits: ViewLimits | None = None,
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
        if open_preview is not None:
            warnings.warn(
                'open_preview is deprecated: use preview_panel="open" (or "closed")',
                DeprecationWarning,
                stacklevel=2,
            )
            if open_preview:
                preview_panel = "open"
        _check_choice("tree_view", tree_view, _PANEL_STATES)
        _check_choice("preview_panel", preview_panel, _PANEL_STATES)
        _check_choice("layout", layout, _LAYOUTS)
        # Fixed: the frontend only opens and closes the tree (_validate_tree_view).
        self._tree_disabled = tree_view == "disabled"
        # The functions given to on_change() and on_query_change(), and what
        # they last heard of (see _changed, _query_changed); first, as the
        # traits set up below call them.
        self._change_callbacks = Callbacks()
        self._change_basis: tuple[str, str, tuple[str, ...]] | None = None
        self._query_callbacks = Callbacks()
        self._query_basis: tuple[DataQuery, dict[str, Any]] | None = None
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
        # The plugins' components come after those given and before the
        # defaults (see plugin.py); a plugin that cannot be loaded is left out.
        self._plugins, problems = load_plugins(plugin_options)
        # Also shown in "About", for the plugins left out.
        self._plugin_problems = problems
        for problem in problems:
            warnings.warn(problem, RuntimeWarning, stacklevel=2)
        components = PluginComponents(self._plugins)
        # How files are moved, copied, deleted and downloaded (see filesystems/),
        # and the jobs doing it in the background (see _jobs/runner.py).
        # What filesystems reach, their URLs and back (see filesystems/).
        self._mappers = MapperChain(
            [*(filesystem_mappers or ()), *components.mappers, *default_mappers()]
        )
        self._operations = OperationChain(
            [*(operations or ()), *components.operations, *self.default_operations()]
        )
        self._jobs = JobRunner(self._send_job)
        # "Properties" counts files with jobs of its own: it changes nothing,
        # so it need not wait for a move or a copy to end.
        self._scans = JobRunner(self._send_job, prefix="scan")
        # The reads behind previews, in threads of their own: a view taking
        # minutes (e.g. a Spark session starting) leaves the kernel free and
        # waits for no job (see _jobs/loader.py).
        self._loader = Loader()
        # The preview loading, if any: cancelled by the next one.
        self._preview_load: Load[Any] | None = None
        # The current directory's items, kept for "list" requests (and paths).
        self._full_listing = Listing(self._make_listing("", []))
        self._listing_version = 0
        # The item detected last, shared by a click's selection, menu and
        # preview (see PreviewsMixin._detection).
        self._detected: tuple[tuple[int, str], float, _Detected | None] | None = None
        # How many times _detected was forgotten: a detection made in a
        # worker is kept only if it was not forgotten meanwhile.
        self._detections_forgotten = 0
        # The detections running, by (id(fs), path): shared by a click's
        # selection, menu and preview (see PreviewsMixin._detection).
        self._detections_running: dict[tuple[int, str], Future[Any]] = {}
        # The selection's detection, if running: cancelled by the next one.
        self._selection_load: Load[Any] | None = None
        # Data browser: path -> the data being queried.
        self._queries: dict[str, DataQuery] = {}
        # A table set previewed (TableSetView): path -> its tables.
        self._table_sets: dict[str, TableSet] = {}
        # The view the preview panel shows, if not the data browser's (whose
        # query owns its view): closed when the panel shows something else.
        self._preview_view: View | None = None
        # Views in tabs of their own ("view_tab"): model id -> widget,
        # kept here while the tab is open.
        self._view_tabs: dict[str, DataExplorer | TableSetTab | ViewTab] = {}
        # Their loads still running, by "load_id": cancelled if the tab closes.
        self._view_tab_loads: dict[str, Load[Any]] = {}
        self._view_tab_ids = itertools.count(1)
        # The launcher's settings file and the function creating it (see
        # _offer_settings); None in notebooks.
        self._settings_file: tuple[str, Callable[[], Any]] | None = None
        # How the formats' data is handled: each job by the first support
        # installed, with its options (see formats/support.py); the formats
        # files are detected as are the supports', and the standard ones.
        self._supports = SupportChain(
            [*(supports or ()), *components.supports, *self.default_supports()],
            format_options,
            formats=[*components.formats, *DEFAULT_FORMATS],
            engine_preference=engine_preference,
        )
        self._formats = self._supports.formats
        # The folder shown's format, if any (see _show_current_format).
        self._current_dir_format: DataFormat | None = None
        self._view_limits = view_limits or ViewLimits()
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
        icons, svgs = format_icons(self._formats)
        super().__init__(
            _height=height,
            _tree_view=tree_view,
            _preview_panel=preview_panel,
            _layout=layout,
            # The user's last choice for this layout (the validator keeps the
            # columns the list has), else its default.
            _columns=_DEFAULT_COLUMNS[layout]
            if (remembered := self._states.columns(layout)) is None
            else remembered,
            _format_labels={f.name: f.label for f in self._formats},
            _text_formats=[f.name for f in self._formats if isinstance(f, Text)],
            _format_icons=icons,
            _file_icon_svgs=svgs,
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
        # The engines, and the one chosen: the user's last if still offered,
        # else the first; before the first listing, which tells what can be
        # previewed with it. Not a choice of the user's: _on_engine ignores it.
        engines = self._supports.engines
        self._engines = [{"key": e.key, "label": e.label} for e in engines]
        keys = [e.key for e in engines]
        remembered = self._states.engine
        self._engine = remembered if remembered in keys else (keys[0] if keys else "")
        self._engine_ready = True
        self._filesystem = name  # shows its top level (see _on_filesystem)
        if preview_panel == "open":
            self._preview = {"empty": True}
        if states_error:
            self._error = states_error

    @staticmethod
    def default_operations() -> list[FileSystemOperations]:
        """The file operations tried after those given as ``operations``;
        override it in a subclass to change them.

        Returns
        -------
        list of FileSystemOperations
            By default ``jupyter_storage_explorer.filesystems.default_operations()``:
            ``AtomicMoveOperation``, ``AsyncFsspecOperations``, then
            ``FsspecOperations``, which does every operation, so the explorer
            can always do them.
        """
        return _default_operations()

    @staticmethod
    def default_supports() -> list[type[FormatSupport] | FormatSupport]:
        """The supports tried after those given as ``supports``; override it
        in a subclass to change them.

        Returns
        -------
        list of FormatSupport classes or objects
            By default the classes of
            ``jupyter_storage_explorer.formats.default_supports()``: those
            needing no engine (text, Markdown, JSON and images, and code
            reading them); the engines' come with their plugins. Each gets its
            options from ``format_options``.
        """
        return list(DEFAULT_SUPPORTS)

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
        self._release_preview()
        with self.hold_sync():
            # An open panel stays open, for the files of this storage.
            self._preview = {"empty": True} if self._preview else {}
            self._tree = {}
            top = self._mappers.location_of(self._fs, root)
            self._local_paths = isinstance(top, LocalLocation)
            self._fs_protocol = top.protocol if top else protocols(self._fs)[0]
            self._root_level = self._level_of(root) or ""
            self._root = root
            if self._current_dir == path:
                # Same path string as before (e.g. "/" on both), so no change event lists it.
                self._list(path)
            else:
                self._current_dir = path
        self._changed()

    def _level_of(self, path: str) -> str | None:
        """What the storage makes of folder ``path`` (e.g. "container"), for
        its icon: ``FileSystemMapper.level``; None for a plain folder."""
        try:
            return self._mappers.level_of(self._fs, path)
        except Exception:
            return None  # a mapper's error only costs an icon

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
    def folder_location(self) -> Location | None:
        """The location of the folder shown in the list.

        Returns
        -------
        Location or None
            Its location, from the filesystem's mapper, e.g. an
            ``S3Location``: ``.url`` for fsspec, polars, pandas, etc., and
            ``.path`` for a local folder's plain path. None if it has none.
        """
        return self._location_of(self._current_dir)

    @property
    def selected_locations(self) -> list[Location]:
        """The locations of the selected items.

        Returns
        -------
        list of Location
            In the order selected. Items without one are left out, so the
            list is empty when nothing with a location is selected.
        """
        locations = (self._location_of(p) for p in self._selected)
        return [location for location in locations if location is not None]

    @property
    def folder_url(self) -> str | None:
        """The URL of the folder shown in the list: ``folder_location.url``.

        Returns
        -------
        str or None
            A URL usable with ``fsspec.open``, polars, pandas, etc., e.g.
            "s3://bucket/data" ("file:///home/u/data" for a local folder);
            None if it has none.
        """
        location = self.folder_location
        return location.url if location is not None else None

    @property
    def selected_urls(self) -> list[str]:
        """The URLs of the selected items: those of ``selected_locations``.

        Returns
        -------
        list of str
            In the order selected. Items without one are left out, so the
            list is empty when nothing with a URL is selected.
        """
        return [location.url for location in self.selected_locations]

    def on_change(
        self, callback: Callable[[StorageExplorer], Any], *, remove: bool = False
    ) -> None:
        """Call a function whenever ``folder_location`` or
        ``selected_locations`` changes in the widget.

        That is when the user opens another folder or storage, or selects
        other items, also when items selected are moved or deleted; not for
        filtering, sorting or paging the list. The function is called in the
        kernel's main thread, as the widget's messages are handled: keep it
        quick, e.g. a chart of a small file.

        Parameters
        ----------
        callback : callable
            Called with the explorer, as ``callback(explorer)``. What it prints
            or displays goes to no cell (the kernel answers the widget, not a
            cell): display into an ``ipywidgets.Output`` shown in a cell, as in
            the example. Errors are shown as tracebacks in the same place and
            do not stop the other functions.
        remove : bool, default False
            Stop calling ``callback`` instead.

        See Also
        --------
        on_query_change : A function called when ``query_result()`` changes.

        Examples
        --------
        >>> import ipywidgets
        >>> import polars as pl
        >>> schema = ipywidgets.Output()
        >>> def show_schema(explorer):
        ...     with schema:
        ...         schema.clear_output(wait=True)
        ...         for url in explorer.selected_urls:
        ...             if url.endswith(".parquet"):
        ...                 display(pl.read_parquet_schema(url))
        >>> explorer = StorageExplorer("s3://my-bucket/data")
        >>> explorer.on_change(show_schema)
        >>> display(explorer, schema)
        """
        self._change_callbacks.register(callback, remove=remove)

    def query_result(self, all_columns: bool = False) -> Any:
        """The data the data browser shows in the preview panel, with its
        filters, sort order and hidden columns applied.

        As ``DataExplorer.result()``: built on the data itself, so it covers
        all of it, also after In memory mode, where the browser showed the
        first rows only. Data viewed in a new tab is not the preview panel's:
        its ``DataExplorer`` gives its own. Execute it while the panel shows
        the data: some supports release what their data reads from (e.g. a
        database connection) once the panel shows something else
        (``View.close``). For an item of several tables (a support's
        ``TableSetView``, e.g. a database's), the table chosen in its tree or
        on its tabs, which ``query_table`` names.

        Parameters
        ----------
        all_columns : bool, default False
            Keep the columns hidden in the browser ("Select columns"): only
            the filters and the sort order are applied.

        Returns
        -------
        dataframe or None
            Of the library the data is read with, e.g. a polars LazyFrame,
            not yet executed; None when the preview panel is closed or shows
            no table (another kind of file, or one still loading).

        See Also
        --------
        on_query_change : A function called when this changes.
        query_table : Which table of several this is.
        DataExplorer.result : The same for a dataframe.

        Examples
        --------
        >>> explorer = StorageExplorer("s3://my-bucket/sales", preview_panel="open")
        >>> # ... click a CSV file, filter and sort it in the data browser ...
        >>> explorer.query_result().collect()
        """
        data = self._shown_query()
        return None if data is None else data.result(all_columns=all_columns)

    @property
    def query_table(self) -> str | None:
        """Which table the preview panel shows of an item of several tables
        (a support's ``TableSetView``, e.g. a database's or a workbook's):
        the one chosen in its tree or on its tabs.

        Returns
        -------
        str or None
            The table's ``id`` (``Leaf.id``, e.g. "sales.orders"), also when
            it could not be read (``query_result()`` is then None); None when
            the panel shows no such item.

        See Also
        --------
        query_result : The table's data, with the data browser's settings.

        Examples
        --------
        >>> def show(explorer):
        ...     print(explorer.query_table, explorer.query_result())
        >>> explorer.on_query_change(show)  # also called when another table is chosen
        """
        preview = self._preview
        if preview.get("loading") or not preview.get("table_set"):
            return None
        tables = self._table_sets.get(preview.get("path"))
        return tables.table if tables is not None else None

    def on_query_change(
        self, callback: Callable[[StorageExplorer], Any], *, remove: bool = False
    ) -> None:
        """Call a function whenever ``query_result()`` changes in the widget.

        That is when the preview panel opens another table in the data
        browser (also another of an item's several tables: ``query_table``),
        or stops showing one (closed, or another kind of file
        previewed: ``query_result()`` is then None), and when the user
        changes a filter, the sort order or the columns shown, or reads the
        data again with the reload button; not for paging, column widths or
        switching between Live and In memory. The function is called in the
        kernel's main thread, after the widget has its rows, so the widget
        waits for it before its next request: keep it quick, e.g. a chart of
        a small or aggregated result.

        Parameters
        ----------
        callback : callable
            Called with the explorer, as ``callback(explorer)``. What it prints
            or displays goes to no cell: display into an
            ``ipywidgets.Output`` shown in a cell, as in the example. Errors
            are shown as tracebacks in the same place and do not stop the
            other functions.
        remove : bool, default False
            Stop calling ``callback`` instead.

        See Also
        --------
        query_result : The data the browser shows, with its filters applied.
        on_change : A function called when the folder or the selection changes.

        Examples
        --------
        >>> import ipywidgets
        >>> import matplotlib.pyplot as plt
        >>> chart = ipywidgets.Output()
        >>> def redraw(explorer):
        ...     with chart:
        ...         chart.clear_output(wait=True)
        ...         if (lf := explorer.query_result()) is not None:
        ...             df = lf.collect()
        ...             plt.plot(df["date"], df["amount"])
        ...             plt.show()
        >>> explorer = StorageExplorer("s3://my-bucket/sales", preview_panel="open")
        >>> explorer.on_query_change(redraw)
        >>> display(explorer, chart)
        """
        self._query_callbacks.register(callback, remove=remove)

    def close(self) -> None:
        """Close the widget, with the views it shows: the preview panel's and
        those of its tabs ("View in a new tab"), whose tabs close with it."""
        # Also called on deletion, of explorers whose __init__ failed too.
        if hasattr(self, "_view_tabs"):
            self._release_preview()
            self._release_view_tabs()
        super().close()

    def _changed(self) -> None:
        """Call the ``on_change`` functions if the storage, the folder shown or
        the selection has changed since they last were.

        Called by each one's observer: a change of storage sets the folder,
        and showing a folder clears the selection, so one change sets several
        traits, of which the functions hear once.
        """
        basis = (self._filesystem, self._current_dir, tuple(self._selected))
        if basis != self._change_basis:
            self._change_basis = basis
            self._change_callbacks(self)

    # --- Messages from the frontend ---

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], buffers: Any
    ) -> None:
        """Handle a message from the frontend, by its "type": a request, which
        is answered with a "reply" of the same "rid", or a notice, which is
        not (its effects show in the traits, or in messages of their own)."""
        kind = content.get("type")
        if kind in _QUERY_REQUESTS:
            # In a worker thread, as they may read the data (see _answer_query).
            self._answer_query(content)
        elif kind == "menu_info":
            # In a worker thread too, as detecting the item reads it.
            self._answer_menu_info(content)
        elif (request := self._requests(buffers or []).get(kind)) is not None:
            reply = request(content)
            self.send({"type": "reply", "rid": content["rid"], **reply})
        elif (notice := self._notices().get(kind)) is not None:
            notice(content)

    def _requests(self, buffers: list[Any]) -> dict[str, _Handler]:
        """Request type -> handler(content), giving the reply. ``buffers``: the
        message's binary pieces (a file's piece, for "upload_chunk")."""
        return {
            "vendor": lambda c: _static.vendor_source(c["name"]),
            # The listing has no locations (see _make_listing): asked for
            # when copying, and for the list's tooltips.
            "locations": lambda c: {
                "locations": [self._location_reply(p) for p in c["paths"]]
            },
            "list": self._list_page,
            "view_tab": self._view_tab_request,
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
            "settings_open": self._settings_open,
            "about": lambda c: self._about(),
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
            "preview": self._preview_notice,
            # Answered with one "download" message per file, its bytes attached.
            "download": lambda c: self._download(c["paths"]),
            "job_cancel": self._cancel_job,
            # Files cut here were pasted in another explorer (told by its frontend).
            "changed": lambda c: self._sources_changed(c["filesystem"], c["paths"]),
            "view_tab_closed": self._view_tab_closed,
        }

    def _preview_notice(self, content: dict[str, Any]) -> None:
        # Not sent without a preview panel (preview_panel="disabled"), which
        # the explorer never opens.
        if self._preview_panel != "disabled":
            self._open_preview(
                content["path"], content.get("format"), content.get("engine", ...)
            )

    # --- The folder shown and the selection, set by the frontend (here, as
    # traitlets' observers must be on the class itself, not on a mixin) ---

    @traitlets.observe("_current_dir")
    def _on_current_dir(self, change: dict[str, Any]) -> None:
        self._list(change["new"])
        self._changed()

    @traitlets.observe("_selected")
    def _on_selected(self, change: dict[str, Any]) -> None:
        self._show_selected_format()
        self._changed()

    def _show_selected_format(self) -> None:
        """Set ``_selected_format`` for the items selected: the item's best
        format, if the engine chosen can view it (the Preview button).

        The item's detection may read it, so it runs as a load, sharing the
        click's detection (``_detection``): until it ends, the frontend
        offers no Preview for the item. A later selection cancels it."""
        if self._selection_load is not None:
            self._selection_load.cancel()
            self._selection_load = None
        selected = list(self._selected)
        if len(selected) != 1:
            self._selected_format = {}
            return
        path = selected[0]
        detection = self._detection(path, self._fs)

        def work() -> list[DataFormat]:
            try:
                item = detection.result()
            except Exception:
                return []  # detection is best-effort; a failure just means no preview
            return item.formats if item is not None else []

        def done(formats: list[DataFormat]) -> None:
            viewable = bool(formats) and self._viewable(formats[0])
            self._selected_format = {
                "path": path,
                "format": formats[0].name if viewable else "",
            }

        self._selection_load = self._loader.submit(work, done, lambda _: None)

    @traitlets.validate("_engine")
    def _validate_engine(self, proposal: dict[str, Any]) -> str:
        keys = [e["key"] for e in self._engines]
        if proposal["value"] not in keys and (keys or proposal["value"]):
            raise traitlets.TraitError(
                f"unknown engine {proposal['value']!r}; choose from {keys}"
            )
        return proposal["value"]

    @traitlets.validate("_tree_view")
    def _validate_tree_view(self, proposal: dict[str, Any]) -> str:
        # The frontend's tree button opens and closes the tree; whether there
        # is one at all is the explorer's argument (_tree_disabled). Not the
        # trait's value: ipywidgets validates after setting it.
        value = proposal["value"]
        if value not in _PANEL_STATES or (value == "disabled") != self._tree_disabled:
            state = "has no tree" if self._tree_disabled else "has a tree"
            raise traitlets.TraitError(f"the explorer {state}: not {value!r}")
        return value

    @traitlets.validate("_columns")
    def _validate_columns(self, proposal: dict[str, Any]) -> list[str]:
        return _known_columns(proposal["value"])

    @traitlets.observe("_columns")
    def _on_columns(self, change: dict[str, Any]) -> None:
        """The user chose the list's columns (the settings menu): remember them
        for explorers of this layout."""
        if getattr(self, "_engine_ready", False):
            self._states.remember_columns(self._layout, change["new"])

    @traitlets.observe("_engine")
    def _on_engine(self, change: dict[str, Any]) -> None:
        """The user chose another engine (the settings menu): remember it,
        and show what can be previewed with it, the preview open included."""
        if not getattr(self, "_engine_ready", False):
            return  # set up by __init__
        if change["new"] and change["new"] != self._states.engine:
            self._states.remember_engine(change["new"])
        self._show_selected_format()
        self._show_current_format()
        # A preview still loading is loaded again, with the new engine.
        preview = self._preview
        if preview.get("path"):
            self._open_preview(preview["path"], preview.get("format"))

    @traitlets.observe("_preview")
    def _on_preview(self, change: dict[str, Any]) -> None:
        # Opened, closed (also by the frontend) or another preview: the
        # query shown may have changed. Not while one loads, so that going
        # from one table to the next does not tell of none between them.
        if not change["new"]:
            self._release_preview()  # closed, e.g. by the frontend's close button
        if not change["new"].get("loading"):
            self._query_changed()

    # --- Locations of paths, from the filesystem mappers ---

    def _location_of(self, path: str) -> Location | None:
        """The location of a path of the filesystem shown (its mapper's
        ``to_location``), or None if it has none."""
        return self._mappers.location_of(self._fs, path)

    def _url(self, path: str) -> str | None:
        """The URL of a path of the filesystem shown, or None if it has none."""
        location = self._location_of(path)
        return location.url if location is not None else None

    def _location_reply(self, path: str) -> dict[str, Any] | None:
        """What the frontend gets of a path's location: {"url", "path" (a
        local item's ``os_path``, else None), "location": its JSON, which
        files copied or dragged carry}; None if it has none."""
        location = self._location_of(path)
        if location is None:
            return None
        return {
            "url": location.url,
            "path": location.os_path if isinstance(location, LocalLocation) else None,
            "location": location.to_json(),
        }

    # --- File operations: wrappers of fsspec calls on the filesystem shown
    # (``self._fs``) for listing, reading and writing; the methods above go
    # through them, never through fsspec directly. Moving, copying and
    # deleting go through the operations objects instead (see filesystems/) ---

    def _ls(
        self, path: str, fs: AbstractFileSystem | None = None
    ) -> list[dict[str, Any]]:
        """The items in directory ``path`` (fsspec's ``ls(detail=True)`` entries);
        ``fs``: another filesystem than the one shown, e.g. a viewed item's."""
        infos = (fs or self._fs).ls(path, detail=True)
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
        self._invalidate_cache(path, fs)

    def _invalidate_cache(
        self, path: str | None = None, fs: AbstractFileSystem | None = None
    ) -> None:
        """Forget cached listings (of ``path``, else all), so changes made elsewhere show.
        The item detected last is forgotten too, whatever ``path`` is."""
        self._detected = None
        self._detections_forgotten += 1
        self._detections_running.clear()
        (fs or self._fs).invalidate_cache(path)
