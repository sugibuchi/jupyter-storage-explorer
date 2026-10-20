# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All Python goes through uv (never call `python`/`pip` directly). Node.js comes with the dev dependencies
(`nodejs-wheel`), so `uv run node`, `uv run npx` and `uv run jlpm` work without a Node install.

```bash
uv sync                                             # both workspace packages, editable, with dev dependencies
uv run pytest                                       # the Python tests (tests/)
uv run pytest tests/test_query.py -k range          # one file / matching tests
uv run pytest --cov                                 # with coverage of src/jupyter_storage_explorer
uvx ruff check src launcher/src tests docs/scripts  # lint (ruff is not a dev dependency; config in pyproject.toml)
uvx ruff format src launcher/src tests docs/scripts # format
uv run npx --yes prettier@3.3.3 --write .           # format static/ and the extension's src/ (.prettierignore)
uv run tests/browser/check_js.py                    # the joined JS modules: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py          # the widgets in a real JupyterLab (see below)
uv run jupyter lab                                  # try the widgets in a browser (see notebooks/)
uv run notebooks/make_samples.py                    # regenerate the sample data the notebooks use
```

CI (`.github/workflows/ci.yaml`) runs ruff, Prettier, `check_js.py`, pytest with coverage (uploaded to Codecov) and
compiles the launcher's extension (`jlpm build:lib`: tsc; `yarn.lock` must be up to date) on pull requests and pushes
to `main`. Releases are tag-driven GitHub Actions (see DEVELOPMENT.md, also for the annotated
tag and the release notes' sections); the maintainer pushes the version tag. In the workflows, `astral-sh/setup-uv`
must be pinned to a full version (e.g. `@v10.3.0`): since v8 it publishes no major-version tags.

Python and `static/` changes need no build: restart the kernel. The launcher's JupyterLab extension
(`launcher/labextension/`, TypeScript) is built by hand: `uv run jlpm install` / `uv run jlpm build` there, then
`uv sync` at the root and restart JupyterLab.

## Tests

The Python tests: fixtures in `tests/conftest.py` are `memfs` (a cleared fsspec memory filesystem), `make_target`
(writes a file there and returns its `Target`), and `mem_explorer` and `local` (explorers of those). Anything polars
reads by URL (`query`, polars previews, the data browser) needs real local files (`tmp_path`), as polars cannot read
`memory://`. The data browser's tests run each filter on polars, pandas, PyArrow, DuckDB and sqlframe (the PySpark API
on DuckDB, which narwhals queries as it does Spark; real Spark needs Java, so it is not tested). The widget tests
subclass the widget to capture `send()` and drive it through `_on_custom_msg`, as the frontend would; for
`StorageExplorer`, in `tests/test_explorer_*.py` (a file per feature, as its mixins) on the harness of
`tests/explorers.py` (`Explorer`, `make`, `entries`, ...).

The JavaScript has no unit tests. `check_js.py` joins each widget's module as the kernel does (`_static.esm`) and runs
`node --check` and ESLint on it (names used but defined in no file, or defined but unused). Behaviour is checked by the
smoke test, `tests/browser/smoke.py` (or some of its checks, by name): it runs JupyterLab with the demo data of
`docs/scripts/` (`_lab.py`, `demo_data.py`) and clicks through the main features in the installed Edge with
Playwright, leaving `tests/browser/smoke-<check>.png` for a failed check. Run it after any change to `static/` or the
extension, and add a check for a new feature there. For a one-off look, write a Playwright script on `_lab` the same
way (a new notebook each time: a reused name reuses its kernel, which keeps the old JavaScript). Drag and drop in the
widgets only works in a browser, not in IntelliJ's notebook view. The smoke test reloads the page and restarts a
launcher tab's kernel (`launcher_tab_reload`, `launcher_tab_restart`); check a server restart by hand (stop and start
its process).

## Layout

A uv workspace of two packages released together (version from git tags via hatch-vcs); the launcher requires the
explorer of exactly its own version (`launcher/hatch_build.py` sets its dependencies; add new ones there):

- `jupyter-storage-explorer` (root, `src/jupyter_storage_explorer/`): the anywidget widgets `StorageExplorer` (files)
  and `DataExplorer` (a dataframe given by the user, any library narwhals supports, with `QuerySettings`). Runtime
  dependencies are only anywidget, fsspec, narwhals, pygments, traitlets; polars, pandas, pyarrow, deltalake, fastexcel,
  openpyxl, Pillow, PySpark are all optional and probed at run time. The "abfs" extra adds adlfs and the Data Lake SDK,
  for `filesystems/abfs.py`. Its top level has the widgets (`storage_explorer.py`, `data_explorer.py`), the
  `Location` interface (`location.py`) and small
  private helpers (`_paths`, `_infos`, `_json`, `_static`, `_callbacks`); the rest is in packages: public, `filesystems/`
  (`locations.py`: the predefined locations; `mapper.py`: the `FileSystemMapper` interface and `MapperChain`; `mappers.py`: the predefined mappers;
  `operation.py`: the `FileSystemOperations` interface; `operations.py`: the predefined operations; `abfs.py`: the
  opt-in Data Lake operation) and `formats/`; private, `_explorer/`
  (`StorageExplorer`'s mixins, with `states.py`, `listing.py` and `jupyterlab_files.py`), `_jobs/` (`tasks.py`:
  `FileTasks`; `runner.py`: `JobRunner`; `incoming.py`, `properties.py`, `transfer_policy.py`) and `_query/`
  (`filters.py`, `settings.py`: `QuerySettings`, `QueryState`; `data_query.py`: `DataQuery`, `fetch_rows`). Users import
  from the top level, `filesystems`, `formats` and `formats.supports` only.
- `jupyter-storage-explorer-launcher` (`launcher/`): a JupyterLab launcher item opening a tab whose kernel runs
  `launch()`. It merges every `storage-explorer/launcher.py` in Jupyter's config paths as layers, system to user
  (their `filesystems()`, `formats()`, `supports()`, `format_options()` (merged by library, format, then option), `operations()`, `filesystem_mappers()`, `transfer_policy()`, `parameters()`;
  `final()` names what later layers cannot change; a retired `style()` is ignored with a warning, `RETIRED`; see `load_settings`, tested in
  `tests/test_launcher.py`). The tab's explorer gets a settings button (`_offer_settings`, trait `_settings_path`;
  never in notebooks) opening the user's `launcher.py` through the `files.ts` drive, created from
  `launcher_template.py` if missing, once the user confirms (`"settings_open"`: `{"missing"}`, then with `"create"`; `"jupyterlab_get"`/`"jupyterlab_save"` with `"settings"` read
  and write that file only): `~/.jupyter` is hidden, so JupyterLab's own contents API would refuse it. Its JupyterLab extension has four plugins:
  - `index.ts`: the tab, a console (`ExplorerTab`). ipywidgets binds a console's widgets to its first kernel, so a tab
    whose session is lost (server restart) or whose kernel changes or restarts is replaced by a new tab. Each tab's
    view (storage, folder per storage) is reported by the explorer as a bubbling `"jupyter-storage-explorer:view"` DOM
    event, kept in JupyterLab's state database (saved with the workspace) and passed back as `launch(view=...)`
    (`StorageExplorer._restore_view`).
  - `download.ts`: files dragged from any explorer onto JupyterLab's file browser are downloaded to the Jupyter server.
  - `files.ts`, "Open in JupyterLab": a JupyterLab drive (`StorageExplorer:<storage>/<path>`, not shown in the file
    browser) serving only the files explorers opened on the page, read and saved through the explorer's kernel
    (`"jupyterlab_get"`, `"jupyterlab_save"`; contents models in `_explorer/jupyterlab_files.py`, whose hash lets
    JupyterLab detect changes made elsewhere before saving; notebooks' cells are trusted as jupyter_server trusts them,
    with nbformat's notary in the kernel: untrusted unless signed, signed when saved trusted; tests get their own
    `JUPYTER_DATA_DIR`). Anything else (typed paths, new files, renames) is refused.
  - `queryTabs.ts`, "Query data in new tab": the kernel opens a `DataExplorer` of the same query
    (`DataExplorer._of_query`, settings remembered by URL as the preview's) and keeps it in `_query_tabs` until the
    tab closes (`"query_tab"`, `"query_tab_closed"`); the tab renders it with the output renderers of the notebook or
    console holding the explorer (ipywidgets ties widgets to that kernel connection), and closes with it or a kernel
    restart.

## Architecture

**Widgets.** `storage_explorer.py` and `data_explorer.py` are `anywidget.AnyWidget` subclasses. State shared with the
browser is in `traitlets` tagged `sync=True` (underscore-prefixed). Everything else is custom messages, dispatched by
`type` in `_on_custom_msg`: requests (`{"type": ..., "rid": ...}`, handled by `_requests()`) are answered with
`{"type": "reply", "rid": ..., ...}`; notices (`_notices()`) are not, their effects showing in the traits (or, for
"download", in a message per file, its bytes attached). Uploads carry file pieces in binary `buffers`. A reply's
error is `{"error": text}` (`error_text`: the explorer's own refusals, ValueErrors, without their type), except for
file operations, whose results have lists, `{"errors": [...]}`, as jobs' do. Values sent go through
`_json.jsonable`. Users' functions (`on_change`; `StorageExplorer.on_query_change`) are kept in `_callbacks.Callbacks`
and called once per change, compared with what they last heard of (`_changed`: storage, folder and selection, from
the traits' observers; `_query_changed`: the query shown in the preview panel and its `result_settings()`, after the
data browser's replies and on `_preview` changes, not while one loads).

`StorageExplorer` keeps its state (set up in `__init__`), the messages' routing, the traitlets observers (they must be
on the class itself), the locations of paths (`_location_of`, from its `MapperChain`; `_url`, its URL; `_data_url`,
what formats read: the URL, but a local file's plain path, until formats take locations; `_location_reply`, what the
frontend gets) and the fsspec calls. Its features are mixins in `_explorer/`,
listed before `AnyWidget` in its bases, which only hold methods: `FoldersMixin` (`folders.py`: the list and the tree),
`PreviewsMixin` (`previews.py`: previews, the data browser, query tabs, the right-click menu's formats),
`BookmarksMixin`, `JupyterLabFilesMixin` (`jupyterlab.py`), `JobsMixin` (`jobs.py`: running file operations as jobs,
following what they change) and `FileRequestsMixin` (`requests.py`: the requests for file operations). What they share
is in `_explorer/common.py` (`Storage`, `open_storage`, `within_top`, `error_text`, `explorers`).

**Frontend.** Plain ES modules in `static/`, no bundler. anywidget cannot import neighbouring files, so `_static.esm()`
concatenates `icons.js` + `common.js` + `query.js` + the widget's parts (`static/<widget>/*.js`, if any) +
`<widget>.js` (all but the last only define functions and constants; the widget's file has `render` and the
`export`), and likewise for CSS (without parts). The storage explorer's parts are a feature each (`tree.js`,
`list.js`, `preview.js`, `item_menu.js`, `operations.js` with the clipboard, `transfers.js` (drag and drop, uploads,
downloads), `jupyterlab.js`, `properties.js`, `toolbar.js` with unsafe mode and bookmarks, `jobs.js`, `overlays.js`
(busy screen, modal, menus), `sections.js` (preview sections), `util.js`): a `createX(x)` returning its elements and
functions. `x` is the explorer, made in `render()`: what the features share (`model`, `el`, `request`, `ask`,
`flash`, `navigate`, ...) and the features themselves (`x.list`, `x.preview`, ...), used when needed, not when made,
so their order rarely matters. Third-party code is vendored in `static/vendor/`. File names, paths and messages naming files are shown through
`visible()` (`common.js`: control, bidi and invisible characters as `\uXXXX`), never as they are. The anywidget `model` only supports
`get`/`set`/`save_changes`/`on`/`off`/`send`; Backbone methods like `previous()` throw inside `set` and silently break
sync.

**Storage.** Everything is an fsspec filesystem; `StorageExplorer` can hold several named ones (`filesystems=`).
Where files are is a `Location` (`location.py`): independent of fsspec's implementations, so it travels to other
kernels, files and libraries doing their own I/O. A frozen, keyword-only dataclass, normalized when made (hosts and
accounts in lower case, endpoints as origins, no trailing "/"; whether it is a folder is not part of it), so equal
locations name the same item and are dict keys. A subclass gives only its fields, `kind` and `url` (the common form,
which the fsspec implementation also reads); `protocol` comes from the URL, and `to_json()`/`Location.from_json()`
(`{"kind", "url", ...fields}`; subclasses register by `kind`; an unknown kind becomes an `FsspecLocation`, the URL in
the JSON being ignored for known kinds). Locations do not say which storage they are on: what one fsspec instance
reaches depends on the implementation (adlfs reaches an account's containers; Azure has a file system per
container), so only mappers tell it (`path_of`). The
predefined ones are in `filesystems/locations.py`: `AbfsLocation` (account, container, path, endpoint suffix:
`abfs://container@account.dfs.core.windows.net/path`; adlfs's `abfs://container/path` with an emulator),
`S3Location` (bucket, key, endpoint or AWS partition: `s3://bucket/key`), `GcsLocation`, `SftpLocation` (host, port,
user, path), `LocalLocation` (`path` as fsspec names it, "C:/x" on Windows, `os_path` the system's form, hostname
and machine id: `file:///...`), `MemoryLocation` (path, process), `FsspecLocation` (fsspec's URL, for filesystems
no mapper knows). Locations come from mappers (`filesystems/mapper.py`, the `filesystem_mappers=` argument,
then `default_mappers()` of `mappers.py`): a `FileSystemMapper` per fsspec implementation, matched by qualified class names through the MRO
(so optional packages are not imported; tests fake s3fs, gcsfs, fsspec's SFTP and sshfs classes by `__module__`). It gives
`to_location(fs, path)` (no credentials; locations are defined per kind of storage, so implementations of one agree:
SFTP's from fsspec's and from sshfs's `fs.storage_args`/`storage_options`; "" gives the top folder; None for items
without one) and `path_of(fs, location)`, the reverse, None unless `fs` reaches it, which each concrete mapper decides
from the location's fields and the instance's settings (the account and cloud, the endpoint or partition, the
server, port and user, the machine, the process). `MapperChain` (`mapper.py`, the explorer's `_mappers`: its mappers
then the defaults) asks them: `location_of`, `path_in`, `same_filesystem` (each reaches the other's top folder, so
the same storage opened with other credentials is one; unknown filesystems, `FsspecMapper`, compare as fsspec does) and
`locate(location, filesystems)`, for files pasted from another kernel: the first of the explorer's storages that
reaches it, else, for kinds other than `FsspecLocation` (never those: the kernel would connect wherever a dropped
URL points), `url_to_fs(location.url)` if it reaches it, else refused (so another kernel's memory or another
machine's disk is never read). `DirFileSystem`s are not mapped: the chain unwraps them, so
their locations are those of the filesystem they wrap, and `same_filesystem` also compares their folders. File operations
are told by `FileTasks` with `move`'s and `copy`'s required keyword `same` (the explorer's chain); outside an
explorer, callers pass it themselves (e.g. the module-level `same_filesystem`, of the default mappers).

**File operations.** `StorageExplorer` ends with a *File operations* block: the only methods that call fsspec on the
filesystem shown (`self._fs`) for listing, reading and writing (`_ls`, `_info`, `_exists`, `_isdir`, `_read_bytes`,
`_write_bytes`); other methods go through them. Moving, copying, deleting, downloading and creating folders go through
the operations objects instead (`filesystems/operation.py`, the `operations=` argument): a chain of `FileSystemOperations`, each
method tried in order until one does not raise `FileSystemOperations.NotSupported` (its own exception, so that a
library's `NotImplementedError` is reported as an error). `operations=` are tried before
`StorageExplorer.default_operations()` (`default_operations()` of `operations.py`, with them): `AtomicMoveOperation` (only moves within a
filesystem whose `mv` renames a folder in one step: local, memory, or a `DirFileSystem` over them), then
`AsyncFsspecOperations` (async filesystems such as s3fs, their coroutines, many files at a time), then
`FsspecOperations`. Both of the latter walk folders themselves, moves included, to report progress
file by file (helpers in `filesystems/_common.py`). `prepare_folder_copy` refuses a folder whose files' paths in it have `.` or `..` parts (object stores keep
such keys; written to a local disk they would leave the target folder), before writing anything. Opt-in, not a default: `AzureDataLakeGen2Operation` (`abfs.py`,
the "abfs" extra), which moves (renames) and creates folders on accounts with a hierarchical namespace with the async
Data Lake SDK, and copies within an account on the server (Copy Blob, `start_copy_from_url`, with a Blob client made from
the Data Lake client's `url` and `credential`, polled until it ends; a folder's files at once, in a `TaskGroup`, at most `concurrency` at a time;
a failed or cancelled copy aborted and deleted), connected from the adlfs filesystem's settings and run on its loop with `fsspec.asyn.sync`; tested with
a fake client (`tests/test_abfs.py`); `filesystems/__init__.py` does not import it. `move` and `copy` take a source
and a target filesystem, the same one or not (keyword `same`, see Storage).
Between filesystems, single files go through `FileSystemOperations._copy_file` and `_move_file`
(`_copy_file_async`/`_move_file_async` in the async class), overridable: by default through a temporary file, so a
failure leaves no partial file, and a move copies then deletes each file, so a cancel leaves each file in one place.
Tests use fsspec's `AsyncFileSystemWrapper` around a memory filesystem as an async one. Object stores (S3, GCS) have
no empty folders, which matters for creating folders.

**Jobs.** Move, rename (a move within the folder), delete, paste, uploads (from JupyterLab's file browser, and the
storage half of uploads from the computer) and both downloads to JupyterLab run in the background (`_jobs/runner.py`).
Each is planned by a `FileTasks` method (`_jobs/tasks.py`, no widget involved) on the main thread: checks, conflicts to
ask about (returned as a dict), else a `Task` whose `work(progress)` runs in the `JobRunner`'s worker thread (one job at
a time) and records what it changed as each item is done (`Task.record`, under a lock). `JobsMixin` starts it
(`_plan_request`, `_start`) and shows those changes on the main thread: as the job goes (`_follow`, before progress
reports: items gone are dropped from the list and tree without listing, at most every `_FOLLOW_INTERVAL`; folders with
new items are listed again, keeping the selection, at most every `_RELIST_INTERVAL`), and all of them once it has ended
(`_finish`). Work functions must not touch traits or `send`; they report to the `Progress` and stop when
`progress.check()` raises `OperationCancelled`. A drop from JupyterLab's file browser is a copy from the kernel's local
disk (`FileTasks.upload`); files from the computer arrive in pieces (`_jobs/incoming.py`), and the last piece starts
`FileTasks.upload_file`. Requests answer `{"job": id}`; the kernel sends `{"type": "job", ...}` as the job runs and with
its result when it ends, which the frontend's `x.jobs.result()` waits for. The main thread is reached through the
kernel's asyncio loop (`call_soon_threadsafe`); without a running loop (tests), jobs run synchronously, so tests see the
result at once. Path helpers are in `_paths.py`.

**Properties** (`_jobs/properties.py`). One file: its fsspec info, answered at once. Folders or several items:
`FileTasks.properties` adds up the operations' `measure` of each item (`properties.scan`), as a job on a `JobRunner`
of its own (`_scans`, ids `scan-N`), so it never waits for a move; the frontend shows it in a blocking dialog with
Cancel (not in the jobs above the status bar). It is not an operation: it does not take unsafe mode.
`FileSystemOperations.measure(fs, path, progress=None)` returns a `Measurement` (files, bytes, folders, oldest and
newest files, errors, `complete`): without `progress` (before a job's work, for its progress bar) the defaults make one
recursive `find`; with it, they list folder by folder (`_common.measure_by_folder`; async: `concurrency` folders at a
time), reporting files found, leaving unlistable folders in `errors` (not `fs.walk`, whose `on_error` misses
subfolders) and returning what was found, `complete` False, on a cancel. `_infos.mtime` gives the modification time
whichever key a filesystem uses.

**Unsafe mode.** Folder operations (move, copy or cut and paste, rename, delete) are offered only while the "Unsafe
mode" slider in the toolbar is on (trait `_unsafe_mode`). In the frontend, every operation calls `x.unsafe.take()` as
it starts, which turns it off (one operation at a time), and sends whether it was on with its request (`"unsafe"`);
the kernel refuses folders without it (the methods' `folders=` parameter).

**Transfer policy** (`_jobs/transfer_policy.py`). `transfer_policy=` rules (`TransferPolicy`: the first rule whose `src`
and `dest` both `fullmatch`, with their named groups capturing the same text in both, decides; default allow; a rule's
patterns must have the same group names) apply to every copy and move, within a filesystem as well as between
filesystems. They are checked in the kernel only, per item as it is planned: `FileTasks._refused` calls its `check`
(the explorer's `_transfer_error`) from `_plan_moves`, `rename`, `_plan_copies` and `download`, and refused items
become errors while the others go on. URLs come from `_policy_url` (the location's, else fsspec's; files pasted keep
the URL of the location they were copied with, from `_paste_sources`). Transfers with the user's computer use `computer_url(name)`
(`browser:///<name>`): checked in `_download` and `_upload_chunk`. Transfers with JupyterLab's file browser (uploads
from it, both downloads to the server) pass filesystem None to `check` for that side, which `_policy_url` makes
`jupyterlab_url(path)` (`jupyterlab://<absolute path>`), unlike the explorer's own local storage (`file:///`). Not a
security boundary.

**Between explorers and with JupyterLab.** Drags of items from the list carry one type,
`application/x-jupyter-storage-explorer-items`, its value a random id of the drag and nothing else; the drag itself
is kept in the page, and a drop is taken only if it carries that id, so drags from other pages (tabs, windows, sites)
can never name files: a drop on the same explorer moves them, on another of the page copies them as Paste does.
Objects are shared page-wide under `Symbol.for(...)` keys on `globalThis`: `"jupyter-storage-explorer.clipboard"`
(Copy or Cut, for Paste in any explorer), `"jupyter-storage-explorer.drag"` (the drag of items running, `{id,
explorer, unsafe, items}`, the items as the clipboard's: set as it starts, cleared as it ends; targets tell their own
drags from others' before the drop by `explorer`) and
`"jupyter-storage-explorer.explorers"` (the explorers on the page by id, with the `download` the launcher's
`download.ts` calls on a drop onto JupyterLab's file browser); the launcher's `files.ts` and `queryTabs.ts` put their
functions (`canOpen`, `open`,
`openWidget`) under `"jupyter-storage-explorer.jupyterlab"`, which the explorer offers ("Open in JupyterLab", "Query
data in new tab") only when they are there. Explorers on a page may be in different kernels (notebooks). The
clipboard names the explorer and storage copied from (`{name}`), and each file's path and location (its JSON, from
the `"locations"` request: `_location_reply`): an explorer of the same kernel is found in `explorers` (by
`_explorer_id`) and its filesystem object used as it is (`_paste_sources`); otherwise the files' locations are found
with `MapperChain.locate`. Copy also puts local items' plain paths (`os_path`), others' URLs, on the system clipboard;
"Copy path" (and the bookmarks menu's) is offered on local storages (trait `_local_paths`). After pasting files cut in another explorer, the frontend dispatches a
`"jupyter-storage-explorer:changed"` event on `globalThis`, so that explorer asks its kernel to show what is left
(`"changed"`, `_sources_changed`).

**States** (`_explorer/states.py`). `ExplorerStates` keeps what explorers remember: bookmarks (storage name, folder, and
its location when bookmarked, as `_location_of` only resolves the storage shown) and the data browser's queries
(keyed by location, or a string such as `DataExplorer`'s; URL, location JSON, settings, mode chosen), the most recent
first, at most `max_queries`. Entries with a URL only (from strings, or written before locations, when local files'
URLs were plain paths) still match a location of that URL or plain path (`_is_query_of`), and are rewritten with
the location at their next change. One in memory (`default_states`) is shared by the kernel's
explorers unless `states=` gives another, or a file's path (`explorer_states`: one object per file in the kernel). With
a path it is a JSON file shared with other kernels (each launcher tab is one; the launcher defaults to
`<jupyter_config_dir>/storage-explorer/states.json`): read again when an explorer is created and before each change,
then written whole, so kernels do not undo each other's changes; a file that cannot be read is never written over.
`DataQuery` remembers through it; `DataExplorer` uses a private one. The frontend asks for the bookmarks when the
bookmarks (star) menu opens (`"bookmarks"`, ...), as other explorers may have changed them.

**Lists.** The file list is filtered (by name), sorted and paged (100 per page) in the browser, from the full listing
the kernel sends; the selection survives filtering and paging. Folders can hold tens of thousands of items, so the
listing (`_listing`, see `_make_listing`) is sent as columns, without paths or URLs: the frontend joins paths and asks
for locations (`"locations"`) when copying and for tooltips, and sorts once per listing, not per keystroke. Folders of more than
`max_browser_items` are handled by the kernel instead (`_explorer/listing.py`): `_listing` then only gives their size
and a version, and the frontend asks for pages (`"list"`), filtering the rows shown while it waits; sorting and filters
there follow the browser's as closely as Python allows (natural order ignoring case and accents; Python's `re`). Filters
(the list's; *Select columns*) use `createFilter` in `common.js`: text or a regular expression, always case-insensitive.
The list's is cleared when another folder's listing arrives, not on the click, so the previous folder's items never show
unfiltered.

**Formats** (`formats/`). Laid out as `filesystems/`: the interfaces `DataFormat` (`base.py`, with `Target`,
`Recipe`, `detect`, `FILE_ICONS`, and the generated code's helpers), `FormatSupport` (`support.py`, with `SupportChain` and `Capability`) and `Requirement`
(`requirement.py`); a module per predefined format (`delta.py`, `parquet.py`, `excel.py`, `text.py`, `images.py`) and
per library of the predefined supports in `supports/` (`polars.py`, `pandas.py`, `pyspark.py`, `fsspec.py`,
`pillow.py`; `python.py` for those needing no package; named after the libraries, which they import only inside
methods; exported by `formats.supports`, not `formats`); the predefined packages in `requirements.py`, the
previews in `preview.py` (tables from dataframes in `frames.py`), the generated code's helpers in `base.py`
(`snippet_options`, `format_kwargs`, `spark_url`), and the defaults in `utils.py` (`DEFAULT_FORMATS`,
`DEFAULT_SUPPORTS`, `create_supports`). A format only detects; a support handles one format's data with one library,
so a library is added to a format (e.g. DuckDB for Parquet) without touching it.
- `DataFormat` subclasses declare `name`, `label`, `priority`, `extensions`, `file_icon` (its files' icon in the list:
  one of `FILE_ICONS`, or `(name, svg)` for one of its own, shown as an `<img>` so its scripts never run; sent as
  `_format_icons` and `_file_icon_svgs`, checked by `format_icons()`; files of formats without one, e.g. Text's, get
  their extension's icon, `FILE_ICON_EXTENSIONS` in `icons.js`) and implement `matches(target)`: cheap detection,
  called on every click; directory formats (Delta, Parquet datasets) inspect `target.children`. Parquet also takes
  Hive-style partition folders (`year=…/month=…/`), followed down one branch (one more `ls` per partition column,
  `_partitioned_layout`), and keeps each directory's `ParquetLayout` by URL for the supports' `query`, which gets the
  URL only (`layout(url)`; a URL it has not seen is detected again through fsspec, `_discover`). The highest
  `priority` wins (Delta 20 > Parquet 10 > default 0 > Text -10). What supports share about a format is on it
  (`Csv.separator`, `Text.language`, `Image.mime_type`, `Parquet.data_url`, ...).
- `FormatSupport` subclasses declare `format` (matched with `isinstance`, so subclasses too: `MarkdownByPython` comes
  before `TextByPython`), `use` (the library's `Requirement`, None for none; names its code, `library()`, and its
  options), `additional_requirements`, and `capabilities`, the names of the methods it implements (`"preview"`,
  `"query"`, `"recipe"`; `Capability`; not "jobs" or "tasks", which are file operations here): the explorer reads only
  `capabilities`, so a method not listed is never called (no runtime check of that, by design: users are expected to
  generate supports with AI from the written rules in `FormatSupport`'s docstring, kept by
  `test_capabilities_are_the_methods_implemented` for the defaults). Each method gets the detected format object first; any may raise `FormatSupport.NotSupported`
  for a target, and the next support is tried. Options are keyword-only `__init__` arguments, no `**kwargs`. Class
  names are `<Format>By<Library>`.
- `SupportChain` (the explorer's `_supports`: `supports=` then `StorageExplorer.default_supports()`, i.e.
  `DEFAULT_SUPPORTS`, ordered format by format, most preferred first) calls them: `preview` and `query` of the
  first support installed for the format (`installed`; `can_query`), `recipes` with the first support with `"recipe"` of each library (so one given replaces the default's),
  installed or not (the code may run elsewhere).
- `preview(fmt, target, limits)`: one `Preview` dataclass (`TablePreview`, `TextPreview`, `TreePreview`,
  `MediaPreview`...) that the frontend renders by `kind` (sent as the one item of the preview's `"sections"`). With no support installed, the chain returns an
  `InstallPreview` naming the missing packages per support, so supports never check.
- `query(fmt, url, is_dir)`: any dataframe narwhals supports, for the data browser (`_new_query`).
  `_query/data_query.py`'s `DataQuery` does filters, sort and paging as narwhals expressions, either on the data itself
  ("live") or on rows read into memory (queried with polars); behaviour such as regex syntax then follows the data's
  library.
- `recipe(fmt, target)`: the code of the "Python code" snippet (a `str`; the chain makes the `Recipe`, adding
  the support's `requirements()`: the frontend gets their packages, names the recipe after the first, "Load with
  polars", and lists them under the code), run as it is in a new notebook: its imports (`import polars as
  pl`, whatever the notebook has), and a Spark session (`SparkSession.builder.getOrCreate()`). It fills a class
  attribute `recipe_template`, written just before the method, an indented `inspect.cleandoc("""...""")`, with
  `str.format`: `{url}` (a repr) and `{kwargs}` (`format_kwargs`, the options; empty when none). Installing packages and
  configuring access to the storage (credentials, Spark's setup for Delta Lake) depend on the environment, so they are
  left to the user. `Requirement`s (`requirements.py`) only say what a support needs (`package`, `import_name`,
  `is_installed()`, `load()`).

**Format options.** `format_options` is `{library: {format name or "*": {option: value}}}` (`create_supports`): a
support class gets its library's (`use.package`) options for `"*"`, then for its `format.name`, only those its
`__init__` takes. Unknown libraries, formats (of the explorer's formats or the supports') and options (taken by no
support of that library and format) are ValueErrors. Supports given as objects are used as they are. Storage options
go into generated code through `snippet_options()`, which drops credential-looking keys and non-literal values. Spark
snippets never get storage options (`spark_url()` rewrites `abfs`/`s3` to `abfss`/`s3a`).

## Conventions

- Comments and docstrings are written in full sentences explaining *why*; keep that density and tone.
- Docstrings of the public API, what users construct, call, subclass or override (`StorageExplorer`, `DataExplorer`,
  `fetch_rows` (the `fetch_rows=` default of both), `QuerySettings`, `ExplorerStates` (with `Bookmark`,
  `QueryState`), `FileSystemOperations` and its subclasses (with `_copy_file`, `_move_file`), `Measurement`,
  `Progress`, `DataFormat`, `FormatSupport`, `Location` and its subclasses, `FileSystemMapper` and its subclasses, `MapperChain`, `same_filesystem`), are in numpy style:
  `Parameters`, `Returns`, `Raises`, `Attributes`, `See Also`, `Examples`. Internal ones (underscore names,
  `DataQuery`, `FileTasks`, `JobRunner`, the mixins, ...) stay prose.
- `from __future__ import annotations` everywhere, with type-only imports under `TYPE_CHECKING` (ruff `TC` rules).
- A new feature of the storage explorer is a mixin in `_explorer/` (Python) and a part in `static/storage_explorer/`
  (JavaScript), each one feature; its tests go in a `tests/test_explorer_*.py` and, for what users do, a check in
  `tests/browser/smoke.py`.
- The root README is the quick start and highlights only; user-facing details are in `docs/storage-explorer.md`
  ("File operation extensions" (a table: add new ones there), "Using the explorer", "Unsafe operations", "Transfer
  policy", "Supported formats", "Format options", "StorageExplorer options") and `docs/data-explorer.md` (the data
  browser, `result()`, `on_change()`, `QuerySettings`, "DataExplorer options"). Update them when operations, formats
  or options change, and the README's highlights for new features. Keep them short.
- Images and links to other files in the READMEs are absolute URLs (`raw.githubusercontent.com/.../main/...` for
  images, `github.com/.../blob/main/...` for files): PyPI shows the README but cannot resolve relative paths. `docs/`
  is read on GitHub only, so it uses relative paths. Screenshots are in `docs/figs/` (the launcher's in
  `launcher/figs/`), taken at 2× and shown at their CSS size with `<img width="...">`. They and the demo GIFs are made
  by `docs/scripts/` (`uv run --group docs docs/scripts/make_all.py`, or one script; see its README): each starts
  JupyterLab in a temporary folder with its own settings, and explorers show a made-up data lake in fsspec's memory
  filesystem (`demo_data.py`), so no local path appears. Change or add a script there rather than taking pictures by
  hand.
